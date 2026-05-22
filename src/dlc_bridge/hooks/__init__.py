"""Hook wrapper modules for DLC SuperCharge.

Each module under :mod:`dlc_bridge.hooks` ports one of the 14 v1.1 PowerShell
hook scripts (``.kiro/scripts/hook-*.ps1``) to Python. They are invoked by
Kiro via the ``.kiro/hooks/*.kiro.hook`` JSON files as::

    uv run python -m dlc_bridge.hooks.<hook_name> [args...]

Every module exposes a ``main(argv: list[str] | None = None) -> int`` entry
point so the hook can also be called directly from Python or from unit tests.

The shared helpers live in :mod:`dlc_bridge.hooks._common`. Hook modules
emit v1.1-byte-identical ``KEY=value`` markers via
:func:`dlc_bridge.util.emit.emit_marker` plus bare terminal tokens
(``HOOK_DONE``, ``HOOK_INIT_DONE``, ``HOOK_REVIEWS_DONE``,
``HOOK_REVIEWS_PARTIAL``, ``HOOK_INIT_SKIPPED``, ``HOOK_FINALIZE_DONE``,
``PROBE_DEBOUNCED``, ``BRIDGE_FAILED``) via
:func:`dlc_bridge.hooks._common.emit_terminal` to match v1.1's
``Write-Output 'HOOK_DONE'`` semantics.

No module ever uses ``shell=True``; every subprocess invocation goes through
:func:`dlc_bridge.hooks._common.invoke_bridge`, which spawns
``python -m dlc_bridge <verb>`` with an argv-list.
"""
