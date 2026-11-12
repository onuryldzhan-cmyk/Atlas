from tools import agent_report


def test_missing_log_is_reported_not_invented(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert agent_report.main([]) == 0
    assert "hafıza kaydı yok" in capsys.readouterr().out


def test_runs_on_repository_records(capsys):
    assert agent_report.main(["--n", "1"]) == 0
    assert "=== CEO" in capsys.readouterr().out
