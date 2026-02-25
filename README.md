# Glade - がおー Website Automation

Instagram自動取り込みシステム for ネオスナック がおー

## 仕組み

GitHub Actionsが毎日朝9時（JST）に自動実行し、`@nakano.gaoo_event` の最新投稿を取得して、[gaooshowlounge.com](https://gaooshowlounge.com) のイベント欄を自動更新します。

## 手動実行

GitHubの Actions タブ → 「Update Instagram Feed」→ 「Run workflow」で即時実行も可能です。

## 必要なSecrets

リポジトリの Settings → Secrets and variables → Actions に以下を設定：

| Secret名 | 値 |
|-----------|-----|
| `FTP_USER` | `main.jp-gladeinc` |
| `FTP_PASS` | Lolipop FTPパスワード |
