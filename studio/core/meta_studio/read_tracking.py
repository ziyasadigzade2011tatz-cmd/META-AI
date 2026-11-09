"""Track verified line ranges for a file snapshot."""


def merge_ranges(ranges):
    result = []
    for start, end in sorted(ranges):
        if start < 1 or end < start:
            raise ValueError("Invalid range")
        if result and start <= result[-1][1] + 1:
            result[-1] = (result[-1][0], max(result[-1][1], end))
        else:
            result.append((start, end))
    return result


def update(coverage, path, sha256, start, end, total):
    if total < 0:
        raise ValueError("Invalid line count")

    state = coverage.get(path, {})
    previous = []
    if state.get("sha256") == sha256:
        if "ranges" in state:
            previous = state["ranges"]
        elif state.get("end", 0) > 0:
            previous = [(1, min(total, int(state["end"])))]

    if total:
        start = max(1, min(start, total))
        end = max(start, min(end, total))
        ranges = merge_ranges([*previous, (start, end)])
    else:
        ranges = []

    contiguous = 0
    for left, right in ranges:
        if left > contiguous + 1:
            break
        contiguous = max(contiguous, right)

    coverage[path] = {
        "sha256": sha256,
        "ranges": ranges,
        "end": contiguous,
        "total_lines": total,
    }

    return coverage[path]


def next_unread(state, batch=300):
    total = state.get("total_lines", 0)
    current = 1

    for left, right in state.get("ranges", []):
        if current < left:
            return current, min(left - 1, current + batch - 1)
        current = max(current, right + 1)

    if current <= total:
        return current, min(total, current + batch - 1)

    return None