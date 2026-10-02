from tools import task_status


def test_missing_log_is_reported_not_invented(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert task_status.main([]) == 0
    assert "görev kaydı yok" in capsys.readouterr().out


def test_lists_repository_tasks(capsys):
    assert task_status.main(["--all"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("{") and "T-0001" in out
