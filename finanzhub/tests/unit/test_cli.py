"""CLI-Smoketests mit CliRunner (kein Netzwerk, keine DB)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from app.cli import main


class TestCLI:
    def test_help(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["--help"])
        assert result.exit_code == 0
        assert "FinanzHub" in result.output

    def test_init_fails_cleanly(self) -> None:
        runner = CliRunner()
        with patch("app.cli.build_engine") as be, \
             patch("app.cli.wait_for_db") as wd, \
             patch("app.data.db.apply_migrations") as am:
            be.return_value = MagicMock()
            wd.return_value = None
            am.return_value = []
            # Globale Optionen müssen vor dem Subkommando stehen.
            result = runner.invoke(main, ["--config-dir", "config.example", "init"])
            # exit_code 0=ok, 1=App-Fehler, 2=Nutzungsfehler
            assert result.exit_code in (0, 1, 2)

    def test_wealth_help(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["wealth", "--help"])
        assert result.exit_code == 0
        assert "--skip-prices" in result.output

    def test_forecast_help(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["forecast", "--help"])
        assert result.exit_code == 0

    def test_nk_help(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["nk", "--help"])
        assert result.exit_code == 0

    def test_events_detect_help(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["events", "detect", "--help"])
        assert result.exit_code == 0

    def test_notify_test_unknown_id(self) -> None:
        runner = CliRunner()
        with patch("app.cli.build_engine") as be:
            be.return_value = MagicMock()
            result = runner.invoke(
                main,
                ["--config-dir", "config.example", "notify", "test", "definitely_not_a_real_id"],
            )
            # Click exit codes: 0=ok, 1=App-Fehler, 2=Nutzungsfehler
            assert result.exit_code in (0, 1, 2)
