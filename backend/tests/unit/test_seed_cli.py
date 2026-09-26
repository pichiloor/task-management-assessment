from datetime import UTC, date, datetime

import pytest

from app.infrastructure import seed


def test_refuses_to_run_unless_explicitly_enabled(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Demo credentials are public: never seed a database by accident.
    monkeypatch.delenv("SEED_DEMO_DATA", raising=False)
    monkeypatch.setattr("sys.argv", ["seed"])

    with pytest.raises(SystemExit) as exc:
        seed.main()

    assert exc.value.code != 0
    assert "SEED_DEMO_DATA" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("utc", "expected"),
    [
        (datetime(2026, 9, 27, 2, 0, tzinfo=UTC), date(2026, 9, 26)),  # 21:00 local
        (datetime(2026, 9, 27, 5, 0, tzinfo=UTC), date(2026, 9, 27)),  # 00:00 local
    ],
)
def test_demo_today_is_the_calendar_date_in_ecuador(
    utc: datetime, expected: date
) -> None:
    assert seed.demo_today(utc) == expected
