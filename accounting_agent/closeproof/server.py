"""Loopback-only BalanceDocket reviewer API and static app server."""

from __future__ import annotations

import hmac
import json
import mimetypes
import secrets
import socket
import stat
import threading
from dataclasses import dataclass
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse

from .advisory import (
    PROVIDER_MANUAL_IMPORT,
    AdvisoryError,
    import_advisory,
    prepare_advisory,
    validate_advisory_envelope,
    write_live_advisory,
)
from .decisions import CloseProofDecisionStore, DecisionError


class CloseProofServerError(ValueError):
    """Raised when the local reviewer server boundary is invalid."""


@dataclass(frozen=True)
class CloseProofRequestPolicy:
    """Same-origin capability policy for the loopback reviewer."""

    allowed_host: str
    allowed_origin: str
    csrf_token: str

    def host_is_allowed(self, headers: Mapping[str, str]) -> bool:
        return hmac.compare_digest(headers.get("Host", ""), self.allowed_host)

    def mutation_is_allowed(self, headers: Mapping[str, str]) -> bool:
        if not self.host_is_allowed(headers):
            return False
        if not hmac.compare_digest(
            headers.get("Origin", ""),
            self.allowed_origin,
        ):
            return False
        if headers.get("Sec-Fetch-Site") not in {None, "same-origin", "none"}:
            return False
        return hmac.compare_digest(
            headers.get("X-CloseProof-CSRF", ""),
            self.csrf_token,
        )


class CloseProofService:
    def __init__(self, *, case_path: str | Path, events_path: str | Path) -> None:
        self.case_path = Path(case_path)
        self.events_path = Path(events_path)
        self.case = self._load_case_file()
        self.decisions = CloseProofDecisionStore(self.case, self.events_path)
        self._mutation_lock = threading.RLock()

    def _load_case_file(self) -> dict[str, Any]:
        try:
            metadata = self.case_path.lstat()
            if not stat.S_ISREG(metadata.st_mode) or self.case_path.is_symlink():
                raise OSError("case path must be a regular file")
            with self.case_path.open("rb") as handle:
                content = handle.read(1_000_001)
            if not 1 <= len(content) <= 1_000_000:
                raise OSError("case size is invalid")
            case = json.loads(content.decode("utf-8"))
            if not isinstance(case, dict):
                raise OSError("case document must be an object")
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CloseProofServerError("BalanceDocket case could not be loaded") from exc
        try:
            validate_advisory_envelope(case, case.get("advisory"))
        except AdvisoryError as exc:
            raise CloseProofServerError("BalanceDocket advisory failed integrity validation") from exc
        return case

    def _reload_case_from_disk_unlocked(self) -> None:
        """Refresh advisory context written by a separate trusted CLI process."""

        loaded = self._load_case_file()
        if loaded == self.case:
            return
        decisions = CloseProofDecisionStore(loaded, self.events_path)
        self.case = loaded
        self.decisions = decisions

    def case_payload(self) -> dict[str, Any]:
        with self._mutation_lock:
            self._reload_case_from_disk_unlocked()
            return self._case_payload_unlocked()

    def _case_payload_unlocked(self) -> dict[str, Any]:
        try:
            decision = self.decisions.latest()
        except DecisionError as exc:
            raise CloseProofServerError(
                "BalanceDocket decision state failed integrity validation"
            ) from exc
        return {**self.case, "decision": decision}

    def record_decision(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._mutation_lock:
            self._reload_case_from_disk_unlocked()
            return self._record_decision_unlocked(payload)

    def _record_decision_unlocked(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise DecisionError("decision body must be an object")
        allowed = {
            "action",
            "rationale",
            "snapshot_sha256",
            "review_context_sha256",
            "finding_id",
            "actor_id",
        }
        required = allowed - {"actor_id"}
        if set(payload) - allowed:
            raise DecisionError("decision body contains unknown fields")
        if not required.issubset(payload):
            raise DecisionError("decision body is missing required fields")
        return self.decisions.record(
            action=payload.get("action", ""),
            rationale=payload.get("rationale", ""),
            snapshot_sha256=payload.get("snapshot_sha256", ""),
            review_context_sha256=payload.get("review_context_sha256", ""),
            finding_id=payload.get("finding_id", ""),
            actor_id=payload.get("actor_id", "demo-controller"),
        )

    def record_decision_and_case(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._mutation_lock:
            self._reload_case_from_disk_unlocked()
            decision = self._record_decision_unlocked(payload)
            return {"decision": decision, "case": self._case_payload_unlocked()}

    def advisory_prompt(self) -> str:
        with self._mutation_lock:
            self._reload_case_from_disk_unlocked()
            request = prepare_advisory(self.case)
            return (
                "Review this synthetic BalanceDocket evidence as an advisory only. "
                "Return exactly one JSON object matching output_schema, without "
                "Markdown fences or extra text. You cannot approve, post, or write "
                "to an ERP.\n\n"
                + json.dumps(request, ensure_ascii=False, indent=2, sort_keys=True)
            )

    def import_manual_advisory(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._mutation_lock:
            self._reload_case_from_disk_unlocked()
            return self._import_manual_advisory_unlocked(payload)

    def _import_manual_advisory_unlocked(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise AdvisoryError("manual import body must be an object", code="invalid_import")
        if set(payload) - {"payload", "reported_model"} or "payload" not in payload:
            raise AdvisoryError("manual import fields are invalid", code="invalid_import")
        reported_model = payload.get("reported_model")
        if reported_model is not None and (
            not isinstance(reported_model, str) or not 1 <= len(reported_model) <= 200
        ):
            raise AdvisoryError("reported model is invalid", code="invalid_import")
        envelope = import_advisory(
            self.case,
            payload["payload"],
            provider=PROVIDER_MANUAL_IMPORT,
            reported_model=reported_model,
        )
        updated = write_live_advisory(self.case_path, envelope)
        # Keep the decision store bound to the same mutable object so its latest
        # event is immediately classified as stale against the new context.
        self.case.clear()
        self.case.update(updated)
        return self._case_payload_unlocked()

    def workpaper(self) -> dict[str, Any]:
        with self._mutation_lock:
            self._reload_case_from_disk_unlocked()
            return self.decisions.workpaper()


def serve_closeproof(
    *,
    case_path: str | Path,
    web_root: str | Path,
    events_path: str | Path,
    host: str = "127.0.0.1",
    port: int = 4173,
    socket_fd: int | None = None,
) -> None:
    if host not in {"127.0.0.1", "localhost"}:
        raise CloseProofServerError("BalanceDocket may bind only to a loopback host")
    if not 1 <= port <= 65535:
        raise CloseProofServerError("port must be between 1 and 65535")
    root = Path(web_root).resolve()
    if not (root / "index.html").is_file():
        raise CloseProofServerError("built BalanceDocket web assets are missing")
    service = CloseProofService(case_path=case_path, events_path=events_path)
    csrf_token = secrets.token_urlsafe(32)
    allowed_host = f"{host}:{port}"
    allowed_origin = f"http://{allowed_host}"
    request_policy = CloseProofRequestPolicy(
        allowed_host=allowed_host,
        allowed_origin=allowed_origin,
        csrf_token=csrf_token,
    )

    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, directory=str(root), **kwargs)

        def end_headers(self) -> None:
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Cross-Origin-Opener-Policy", "same-origin")
            self.send_header("Content-Security-Policy", "default-src 'self'; connect-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; font-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
            super().end_headers()

        def do_GET(self) -> None:
            if not self._host_is_allowed():
                self._json({"error": "host_not_allowed"}, status=HTTPStatus.FORBIDDEN)
                return
            path = urlparse(self.path).path
            if path == "/api/health":
                self._json({"status": "ok", "synthetic_only": True, "erp_writes": False})
                return
            if path == "/api/case":
                try:
                    self._json(service.case_payload())
                except CloseProofServerError:
                    self._json({"error": "case_reload_failed"}, status=HTTPStatus.CONFLICT)
                return
            if path == "/api/session":
                self._json({"csrf_token": csrf_token})
                return
            if path == "/api/advisory/prompt":
                try:
                    self._json({"prompt": service.advisory_prompt()})
                except CloseProofServerError:
                    self._json({"error": "case_reload_failed"}, status=HTTPStatus.CONFLICT)
                return
            if path == "/api/workpaper":
                try:
                    workpaper = service.workpaper()
                except (CloseProofServerError, DecisionError) as exc:
                    self._json(
                        {"error": "case_reload_failed" if isinstance(exc, CloseProofServerError) else str(exc)},
                        status=HTTPStatus.CONFLICT,
                    )
                    return
                self._json(workpaper, attachment="balancedocket-workpaper.json")
                return
            requested = (root / path.lstrip("/")).resolve()
            if path != "/" and (root not in requested.parents or not requested.is_file()):
                self.path = "/index.html"
            super().do_GET()

        def do_POST(self) -> None:
            if not self._mutation_request_is_allowed():
                self._json(
                    {"error": "cross_site_request_blocked"},
                    status=HTTPStatus.FORBIDDEN,
                )
                return
            path = urlparse(self.path).path
            if path not in {"/api/decisions", "/api/advisory/import"}:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
            if content_type != "application/json":
                self._json({"error": "content_type_must_be_application_json"}, status=HTTPStatus.UNSUPPORTED_MEDIA_TYPE)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                length = 0
            maximum = 32_768 if path == "/api/decisions" else 100_000
            if not 1 <= length <= maximum:
                self._json({"error": "request_body_size_invalid"}, status=HTTPStatus.BAD_REQUEST)
                return
            try:
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                if path == "/api/decisions":
                    response = service.record_decision_and_case(payload)
                    response_status = HTTPStatus.CREATED
                else:
                    response = {"case": service.import_manual_advisory(payload)}
                    response_status = HTTPStatus.OK
            except (UnicodeDecodeError, json.JSONDecodeError):
                self._json({"error": "request_body_invalid_json"}, status=HTTPStatus.BAD_REQUEST)
                return
            except DecisionError as exc:
                self._json({"error": str(exc)}, status=HTTPStatus.UNPROCESSABLE_ENTITY)
                return
            except AdvisoryError as exc:
                self._json({"error": exc.code}, status=HTTPStatus.UNPROCESSABLE_ENTITY)
                return
            except CloseProofServerError:
                self._json({"error": "case_reload_failed"}, status=HTTPStatus.CONFLICT)
                return
            self._json(response, status=response_status)

        def _host_is_allowed(self) -> bool:
            return request_policy.host_is_allowed(self.headers)

        def _mutation_request_is_allowed(self) -> bool:
            return request_policy.mutation_is_allowed(self.headers)

        def log_message(self, format: str, *args: Any) -> None:
            return

        def _json(
            self,
            payload: dict[str, Any],
            *,
            status: HTTPStatus = HTTPStatus.OK,
            attachment: str | None = None,
        ) -> None:
            body = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            if attachment:
                self.send_header("Content-Disposition", f'attachment; filename="{attachment}"')
            self.end_headers()
            self.wfile.write(body)

    mimetypes.add_type("text/javascript", ".js")
    if socket_fd is None:
        server = ThreadingHTTPServer((host, port), Handler)
    else:
        if socket_fd < 0:
            raise CloseProofServerError("reserved socket descriptor is invalid")
        inherited_socket = socket.socket(fileno=socket_fd)
        try:
            bound = inherited_socket.getsockname()
            if (
                inherited_socket.family != socket.AF_INET
                or inherited_socket.getsockopt(socket.SOL_SOCKET, socket.SO_TYPE)
                != socket.SOCK_STREAM
                or bound[:2] != ("127.0.0.1", port)
            ):
                raise CloseProofServerError("reserved socket is not the requested loopback port")
            server = ThreadingHTTPServer(
                (host, port),
                Handler,
                bind_and_activate=False,
            )
            server.socket.close()
            server.socket = inherited_socket
            server.server_address = bound
            server.server_activate()
        except Exception:
            inherited_socket.close()
            raise
    print(f"BalanceDocket reviewer: http://{host}:{port}")
    print("Synthetic demo only; network advisory and ERP writes are disabled in the server")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
