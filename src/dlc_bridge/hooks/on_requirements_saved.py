"""Python port of ``.kiro/scripts/hook-on-requirements-saved.ps1``.

Phase 1 -> 2c chain. Three stages:

* ``--stage init`` (default): debounce -> slug -> state init -> bridge
  ``analyze-requirements`` -> id-propagation.
* ``--stage reviews``: dispatch ``review-{security,ux,a11y,performance}``
  in parallel via the bridge for the agent-selected domains.
* ``--stage finalize``: advance state.md to Phase 2c.

Markers: ``STAGE``, ``TRIGGER``, ``SLUG``, ``STATE_INITIALIZED`` /
``STATE_EXISTS``, ``BRIDGE_STARTING=analyze-requirements``,
``BRIDGE_EXIT``, ``BRIDGE_CACHED`` (when the bridge short-circuits on a
cached PRD; surfaced from the subprocess stdout via
:func:`dlc_bridge.hooks._common.surface_bridge_cached`),
``PRD``, ``ID_PROPAGATED`` / ``ID_PROPAGATE_ZERO_MATCHES`` /
``ID_PROPAGATE_NO_ENTRIES`` / ``ID_PROPAGATE_SKIPPED``,
``DOMAINS``, ``REVIEW_STARTING``, ``REVIEW_OK``, ``REVIEW_FAILED``,
``REVIEWS_SKIPPED``, ``STATE_ADVANCED``, ``SELF_WRITE_RECORDED``,
terminal ``PROBE_DEBOUNCED`` / ``PROBE_SELF_FIRE`` /
``HOOK_INIT_SKIPPED`` / ``HOOK_INIT_DONE`` / ``HOOK_REVIEWS_DONE`` /
``HOOK_REVIEWS_PARTIAL`` / ``HOOK_FINALIZE_DONE`` / ``BRIDGE_FAILED`` /
``ERROR``.
"""

from __future__ import annotations

import concurrent.futures as futures
from pathlib import Path

from dlc_bridge.hooks import _common
from dlc_bridge.util import debounce as debounce_mod
from dlc_bridge.util import emit
from dlc_bridge.util import id_propagate
from dlc_bridge.util import self_writes
from dlc_bridge.util import slug as slug_mod
from dlc_bridge.util import state as state_mod

_HOOK_ID = "on-requirements-saved"
_VALID_DOMAINS = ("security", "ux", "a11y", "performance")
_DOMAIN_TO_VERB = {
    "security": "review-security",
    "ux": "review-ux",
    "a11y": "review-a11y",
    "performance": "review-performance",
}


def _parse_domains(raw: str | None) -> list[str]:
    """Split a comma/space-separated domain list; drop empties."""
    if not raw:
        return []
    parts: list[str] = []
    for chunk in raw.replace(",", " ").split():
        chunk = chunk.strip()
        if chunk:
            parts.append(chunk)
    return parts


def _run_review(
    verb: str, source: str, slug: str, dry_run: bool
) -> int:
    """Run a single review bridge invocation; return exit code."""
    result = _common.invoke_bridge(
        verb,
        args=["--source", source, "--slug", slug],
        dry_run=dry_run,
    )
    return result.returncode


def _stage_finalize(args, slug_root) -> int:
    """Run the ``--stage finalize`` branch."""
    try:
        slug = args.slug or slug_mod.from_path(args.source)
    except Exception as e:
        emit.emit_marker("ERROR", f"could not derive slug from {args.source}: {e}")
        return 1
    slug_path = slug_root / slug
    state_path = slug_path / "state.md"
    if state_path.exists():
        state_mod.advance_phase(
            state_path,
            next_phase="2c",
            notes="reviews complete, ready for design",
        )
    emit.emit_marker("SLUG", slug)
    emit.emit_marker("STATE_ADVANCED", "2c")
    _common.emit_terminal("HOOK_FINALIZE_DONE")
    return 0


def _stage_reviews(args, slug_root) -> int:
    """Run the ``--stage reviews`` branch (parallel dispatch)."""
    try:
        slug = args.slug or slug_mod.from_path(args.source)
    except Exception as e:
        emit.emit_marker("ERROR", f"could not derive slug from {args.source}: {e}")
        return 1
    emit.emit_marker("SLUG", slug)

    requested = _parse_domains(args.domains)
    invalid = [d for d in requested if d not in _VALID_DOMAINS]
    if invalid:
        emit.emit_marker("ERROR", f"invalid domain(s): {','.join(invalid)}")
        return 1
    if not requested:
        emit.emit_marker("REVIEWS_SKIPPED", "no domains requested")
        _common.emit_terminal("HOOK_REVIEWS_DONE")
        return 0

    prd = slug_root / slug / "requirements.prd.md"
    if not prd.exists():
        emit.emit_marker(
            "ERROR", f"PRD missing at {prd}; run --stage init first"
        )
        return 1
    emit.emit_marker("PRD", str(prd))
    emit.emit_marker("DOMAINS", ",".join(requested))

    # Dispatch in parallel via ThreadPoolExecutor (one thread per domain).
    exit_codes: dict[str, int] = {}
    with futures.ThreadPoolExecutor(max_workers=4) as pool:
        future_to_domain: dict[futures.Future[int], str] = {}
        for domain in requested:
            verb = _DOMAIN_TO_VERB[domain]
            emit.emit_marker("REVIEW_STARTING", f"{domain} ({verb})")
            future_to_domain[
                pool.submit(_run_review, verb, str(prd), slug, args.dry_run)
            ] = domain
        for fut in futures.as_completed(future_to_domain):
            domain = future_to_domain[fut]
            try:
                exit_codes[domain] = fut.result()
            except Exception:
                exit_codes[domain] = 1

    any_failed = False
    for domain in requested:
        code = exit_codes.get(domain, 1)
        if code == 0:
            emit.emit_marker("REVIEW_OK", domain)
        else:
            any_failed = True
            emit.emit_marker("REVIEW_FAILED", f"{domain} exit={code}")

    if any_failed:
        _common.emit_terminal("HOOK_REVIEWS_PARTIAL")
        return 1
    _common.emit_terminal("HOOK_REVIEWS_DONE")
    return 0


def _stage_init(args, slug_root) -> int:
    """Run the default ``--stage init`` branch."""
    emit.emit_marker("STAGE", "init")
    emit.emit_marker("TRIGGER", args.source)

    debounce_state = (
        Path(args.debounce_state_path)
        if args.debounce_state_path
        else slug_root / "_recent-fires.json"
    )
    proceed = debounce_mod.check_debounce_keyed(
        state_path=debounce_state,
        hook_id=_HOOK_ID,
        trigger_path=args.source,
    )
    if not proceed:
        _common.emit_terminal("PROBE_DEBOUNCED")
        return 0

    try:
        slug = args.slug or slug_mod.from_path(args.source)
    except Exception as e:
        emit.emit_marker("ERROR", f"could not derive slug from {args.source}: {e}")
        return 1
    emit.emit_marker("SLUG", slug)

    slug_path = slug_root / slug
    state_path = slug_path / "state.md"
    if not state_path.exists():
        try:
            state_mod.init_state(state_path, slug=slug)
            emit.emit_marker("STATE_INITIALIZED", str(state_path))
        except Exception as e:  # pragma: no cover - defensive
            emit.emit_marker("ERROR", f"state.md init failed: {e}")
            return 1
    else:
        emit.emit_marker("STATE_EXISTS", str(state_path))

    # Self-fire suppression (Issue #8): if requirements.md's current hash
    # matches a recent self-write (e.g. our own id_propagate from the
    # previous fire), skip the bridge entirely.
    if self_writes.is_self_fire(
        file_path=Path(args.source), slug_root=slug_path
    ):
        emit.emit_marker("PROBE_SELF_FIRE", args.source)
        _common.emit_terminal("HOOK_INIT_SKIPPED")
        return 0

    emit.emit_marker("BRIDGE_STARTING", "analyze-requirements")
    result = _common.invoke_bridge(
        "analyze-requirements",
        args=["--source", args.source, "--slug", slug],
        dry_run=args.dry_run,
    )
    _common.emit_bridge_exit(result.returncode)
    if result.returncode != 0:
        _common.emit_terminal("BRIDGE_FAILED")
        return result.returncode

    cached = _common.surface_bridge_cached(result.stdout)
    if cached:
        emit.emit_marker("BRIDGE_CACHED", cached)

    prd = slug_path / "requirements.prd.md"
    emit.emit_marker("PRD", str(prd))
    if prd.exists():
        try:
            result = id_propagate.propagate_ids(
                dlc_prd=prd,
                kiro_req=Path(args.source),
            )
            _common.emit_propagate_outcome(result, prd=prd, source=args.source)
        except Exception as e:
            emit.emit_marker("ID_PROPAGATE_SKIPPED", f"propagate failed: {e}")
    else:
        emit.emit_marker("ID_PROPAGATE_SKIPPED", f"PRD missing at {prd}")

    # Record the post-init hash of requirements.md so the next fire (triggered
    # by id_propagate's mutation, within the TTL window) can recognise this
    # as a self-write and suppress (Issue #8).
    digest = self_writes.record(
        file_path=Path(args.source), slug_root=slug_path
    )
    if digest:
        emit.emit_marker(
            "SELF_WRITE_RECORDED", f"requirements.md sha256={digest[:16]}"
        )

    _common.emit_terminal("HOOK_INIT_DONE")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Hook entry point. See module docstring for marker contract."""
    parser = _common.common_parser("Hook: on-requirements-saved")
    parser.add_argument(
        "--source",
        required=True,
        help="The triggering requirements.md path.",
    )
    parser.add_argument(
        "--stage",
        choices=("init", "reviews", "finalize"),
        default="init",
        help="Pipeline stage.",
    )
    parser.add_argument(
        "--domains",
        default="",
        help="Comma-separated review domains (used with --stage reviews).",
    )
    parser.add_argument(
        "--dlc-root",
        default=None,
        help="Override .dlc root (used by tests).",
    )
    parser.add_argument(
        "--debounce-state-path",
        default=None,
        help="Override debounce-state json path (used by tests).",
    )
    args = parser.parse_args(argv)

    slug_root = _common.dlc_root_for(args.dlc_root)

    if args.stage == "finalize":
        return _stage_finalize(args, slug_root)
    if args.stage == "reviews":
        return _stage_reviews(args, slug_root)
    return _stage_init(args, slug_root)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
