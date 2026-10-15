from tools.pr_comment import MARKER, render


def rule(name, detected=2, incidents=2, missed=(), ttd=150.0, false_fires=0):
    return {"rule": name, "detected": detected, "incidents": incidents, "missed": list(missed),
            "median_ttd_s": ttd, "false_fires": false_fires, "baseline_hours": 1.0}


def result(*rules):
    return {"faults": 4, "baselines": 1, "rules": list(rules)}


def table_row(text, name):
    return next(line for line in text.splitlines() if line.startswith(f"| `{name}`"))


def test_only_changed_cells_show_an_arrow():
    text = render(result(rule("A", ttd=100.0)), result(rule("A", detected=1, ttd=100.0)), "lib")
    assert text.startswith(MARKER)
    assert table_row(text, "A") == "| `A` | 1/2 → **2/2** | 1m40s | 0.00 |"


def test_new_removed_and_missed_rules():
    head = result(rule("A"), rule("B", detected=1, missed=["inc-1"]))
    text = render(head, result(rule("A"), rule("Old")), "lib")
    assert "| `B` (new) | 1/2 |" in text
    assert "~~`Old`~~ (removed)" in text
    assert "**1 missed detection(s)**" in text and "- `B`: inc-1" in text


def test_without_base_nothing_is_marked_new():
    text = render(result(rule("A")), None, "lib")
    assert "(new)" not in text and "→" not in text
