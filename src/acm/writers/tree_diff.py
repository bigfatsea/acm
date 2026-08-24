# // Ver 2026-08-24 22:05, by gemini-3.7-flash
"""Semantic AST / Tree diff utility for asserting zero unintended mutation of unmanaged fields."""

from typing import Any


def is_path_managed(path: str, managed_paths: list[str]) -> bool:
    """Check if a given dot-path is covered by managed paths.

    Returns True if path exactly equals or is a sub-path of a managed path.
    """
    for mp in managed_paths:
        mp_clean = mp.strip()
        if not mp_clean:
            continue
        if path == mp_clean or path.startswith((f"{mp_clean}.", f"{mp_clean}[")):
            return True
    return False


def is_path_prefix_of_managed(path: str, managed_paths: list[str]) -> bool:
    """Check if path is a parent/ancestor of any managed path."""
    for mp in managed_paths:
        mp_clean = mp.strip()
        if mp_clean.startswith((f"{path}.", f"{path}[")):
            return True
    return False


def compare_trees(
    before: Any,
    after: Any,
    managed_paths: list[str],
    current_path: str = "",
    diffs: list[str] | None = None,
) -> list[str]:
    """Recursively compare before and after data trees, ignoring managed paths.

    Returns a list of human-readable diff descriptions for any unmanaged discrepancies.
    """
    from collections.abc import Mapping

    if diffs is None:
        diffs = []

    # If current path is managed, ignore any differences
    if current_path and is_path_managed(current_path, managed_paths):
        return diffs

    # Numeric equivalence (e.g. 1 == 1.0)
    if isinstance(before, (int, float)) and isinstance(after, (int, float)):
        if before != after:
            diffs.append(
                f"Value mismatch at unmanaged path '{current_path}': {before!r} != {after!r}"
            )
        return diffs

    # Mapping / Dict comparison
    if isinstance(before, Mapping) and isinstance(after, Mapping):
        all_keys = set(before.keys()).union(after.keys())
        for k in sorted(all_keys, key=str):
            sub_path = f"{current_path}.{k}" if current_path else str(k)
            if is_path_managed(sub_path, managed_paths):
                continue

            if k not in before:
                if is_path_prefix_of_managed(sub_path, managed_paths) and isinstance(
                    after[k], Mapping
                ):
                    compare_trees({}, after[k], managed_paths, sub_path, diffs)
                else:
                    diffs.append(f"Unmanaged key added at '{sub_path}': {after[k]!r}")
            elif k not in after:
                if is_path_prefix_of_managed(sub_path, managed_paths) and isinstance(
                    before[k], Mapping
                ):
                    compare_trees(before[k], {}, managed_paths, sub_path, diffs)
                else:
                    diffs.append(f"Unmanaged key removed at '{sub_path}': {before[k]!r}")
            else:
                compare_trees(before[k], after[k], managed_paths, sub_path, diffs)
        return diffs

    # List comparison
    if isinstance(before, list) and isinstance(after, list):
        if len(before) != len(after):
            diffs.append(
                f"List length changed at unmanaged path '{current_path}': {len(before)} -> {len(after)}"
            )
            return diffs
        for idx, (b_item, a_item) in enumerate(zip(before, after, strict=False)):
            sub_path = f"{current_path}[{idx}]"
            compare_trees(b_item, a_item, managed_paths, sub_path, diffs)
        return diffs

    # Type mismatch if one is Mapping/list and the other is not
    if isinstance(before, Mapping) != isinstance(after, Mapping) or isinstance(
        before, list
    ) != isinstance(after, list):
        diffs.append(
            f"Type mismatch at unmanaged path '{current_path}': {type(before).__name__} != {type(after).__name__}"
        )
        return diffs

    # Primitive comparison
    if before != after:
        diffs.append(f"Value mismatch at unmanaged path '{current_path}': {before!r} != {after!r}")

    return diffs


def tree_diff(before: Any, after: Any, managed_paths: list[str]) -> list[str]:
    """Top-level semantic diff returning list of unmanaged modifications."""
    return compare_trees(before, after, managed_paths, current_path="", diffs=[])
