# Changelog

## [Unreleased]

## [1.5.1] - 2026-11-01

- refactor(invoices): remove the multiple-payment toggle

- **403 is no longer reported as an authentication failure.** `PermissionError` (a subclass of `AuthenticationError`, so existing `except` blocks keep working) now carries every 403 — wrong key type, blocked IP, or plain account state such as `whitelist_required`.
- **Base URL must use HTTPS.** Plain HTTP is accepted only against a loopback host, which is what a local integration test points at. The API secret signs every request, so a plaintext base URL put that credential on the wire.

## [1.5.0] - 2026-10-29

- fix(sdk): preserve current refund contracts in TON conformance
- fix(ton): return friendly addresses with existing webhook schema
- feat(sdk-python): add refund create, get, list and iterate

- **403 is no longer reported as an authentication failure.** `PermissionError` (a subclass of `AuthenticationError`, so existing `except` blocks keep working) now carries every 403 — wrong key type, blocked IP, or plain account state such as `whitelist_required`.
- **Base URL must use HTTPS.** Plain HTTP is accepted only against a loopback host, which is what a local integration test points at. The API secret signs every request, so a plaintext base URL put that credential on the wire.

## [1.4.0] - 2026-10-14

- Make the SDK CI tier green
- Fix invoice-late-payment audit findings (tasks 4.1-4.8)
- feat(invoices): accept full late payments without reopening invoices
- fix(sdk-conformance): восемь копий контракта разошлись с каноном — 403 снова permission
- fix(sdk): HTTPS обязателен, а 403 перестал притворяться ошибкой ключа

- **403 is no longer reported as an authentication failure.** `PermissionError` (a subclass of `AuthenticationError`, so existing `except` blocks keep working) now carries every 403 — wrong key type, blocked IP, or plain account state such as `whitelist_required`.
- **Base URL must use HTTPS.** Plain HTTP is accepted only against a loopback host, which is what a local integration test points at. The API secret signs every request, so a plaintext base URL put that credential on the wire.

## [1.3.0] - 2026-08-28

- release: the changelog rot had a cause, and it was not the one I named
- docs(sdk): the READMEs say static wallets, not payment channels
- feat(sdk): payment-channel webhooks and the flow in every README
- feat(python-sdk): payment channels, and a feed reader that cannot stop early
- feat(sdk-conformance): declare the payment-channel operations
- docs(api): pin the empty-body signing rule and fix the published POST vector

## [1.2.0] - 2026-08-28

- release: the changelog rot had a cause, and it was not the one I named
- docs(sdk): the READMEs say static wallets, not payment channels
- feat(sdk): payment-channel webhooks and the flow in every README
- feat(python-sdk): payment channels, and a feed reader that cannot stop early
- feat(sdk-conformance): declare the payment-channel operations
- docs(api): pin the empty-body signing rule and fix the published POST vector

## [1.1.1] - 2026-08-02

- fix(ecosystem): recover SDK releases

## [1.1.0] - 2026-07-21

- feat(docs): make the developer surface consumable by LLM agents

## [1.0.1] - 2026-07-19

- fix: align SDK problem details semantics

## [1.0.0]

- Initial official SDK.
