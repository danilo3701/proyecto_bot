# PR workflow (просто и по шагам)

Этот файл для тех, кто **не программист**: как сделать PR без ручной вставки текста.

## 1) Один раз настроить

Открой PowerShell в папке проекта и выполни:

```powershell
. .\tools\powershell\mkpr.ps1
```

Это подключит команды `mkpr`, `mkp`, `prsame`, `prdraft` в текущую сессию.

---

## 2) Обычный ежедневный сценарий (ОДНА команда)

1. Внести изменения в проект.
2. Выполнить:

```powershell
mkp
```

Если нужен свой заголовок:

```powershell
mkp "fix api timeout"
```


Что произойдёт автоматически:
- перед PR ветка синхронизируется с `main` через `rebase`
- сделается commit
- изменения отправятся в GitHub
- создастся PR
- описание PR возьмётся из шаблона `.github/PULL_REQUEST_TEMPLATE/fix.md`

---

## 3) Если PR ещё не готов (Draft, тоже одна команда)

```powershell
prdraft
```

Если нужен свой заголовок:

```powershell
prdraft "wip onboarding"
```

Draft = черновик PR (его можно проверять, но не надо сразу мерджить).

---

## 4) Если нужно продолжить тот же PR

`mkp`, `prsame` и `prdraft` работают в текущей ветке и перед PR делают rebase на `main`.

---

## 5) Как выбрать тип

- `-Type fix` — исправление ошибки.
- `-Type feature` — новая функциональность.
- `-Type refactor` — переписывание структуры без изменения поведения.

---

## 6) Где лежат шаблоны PR

- Общий шаблон: `.github/pull_request_template.md`
- Типовые шаблоны:
  - `.github/PULL_REQUEST_TEMPLATE/fix.md`
  - `.github/PULL_REQUEST_TEMPLATE/feature.md`
  - `.github/PULL_REQUEST_TEMPLATE/refactor.md`

Если хочешь другой текст PR — меняй эти файлы.

---

## 7) Частые проблемы

### `gh is not installed`
Установи GitHub CLI: https://cli.github.com/

### `gh auth status failed`
Выполни:

```powershell
gh auth login
```

### `No local changes`
Это значит: ты не изменил файлы. Сначала внеси изменения в проект.


---

## 8) Патч для `$PROFILE`: `mergelast_or_close` (вставить как есть)

Открой профиль:

```powershell
notepad $PROFILE
```

Найди старую `function mergelast_or_close { ... }` и **полностью замени** на этот блок (ASCII-текст):

```powershell
function mergelast_or_close {
  $prs = gh pr list -R $global:REPO -S 'is:pr is:open author:@me sort:updated-desc' --limit 1 --json number | ConvertFrom-Json
  if (-not $prs) { 'No open PRs.'; return }

  $pr = $prs[0].number
  $info = gh pr view $pr -R $global:REPO --json mergeable,mergeStateStatus,url | ConvertFrom-Json

  if ($info.mergeable -eq 'MERGEABLE') {
    gh pr merge $pr -R $global:REPO --merge --delete-branch
  } else {
    gh pr close $pr -R $global:REPO --delete-branch --comment 'Closing PR: conflicting/blocked. Latest PR only.'
    "Not merged: $($info.mergeable) $($info.mergeStateStatus)"
    "PR: $($info.url)"
  }
}
```

Сохрани (Ctrl+S) и закрой Notepad.

Перезагрузи профиль:

```powershell
. $PROFILE
```

Быстрая проверка, что применился флаг `--delete-branch`:

```powershell
(Get-Command mergelast_or_close).Definition
```

Важно: если ветка не существует локально, `gh pr close --delete-branch` иногда может ругнуться. Тогда удаление удалённой ветки часто всё равно происходит; если нет — удалите ветку кнопкой **Delete branch** в GitHub UI.
