# Maestro UI fixture flows

These flows exercise the installed `com.bulletfeed.app` APK through the Android accessibility layer, but they are **fixture-level UI regression tests only**. They use `clearState: true` and the Mock/Demo repository state, so they do not prove production API integration, GitHub OAuth, User-knownness, session recovery, private repository permission loss, or release HTTPS behavior.

Install Maestro, connect an emulator or a USB-debuggable device, install the fixture/debug APK, then run the individual flows as needed:

```bash
maestro test maestro/flows/onboarding.yaml
maestro test maestro/flows/feed.yaml
maestro test maestro/flows/filter.yaml
maestro test maestro/flows/notifications.yaml
maestro test maestro/flows/security.yaml
```

Do not use these flows as the PR #81 MVP completion gate. The required real-backend chain is documented in `docs/real-backend-acceptance.md` and must run against FastAPI + source-sync worker with real server state. Any future automated Maestro flow that targets that environment should be kept separate from these deterministic fixture flows and must not embed OAuth credentials or bearer tokens in YAML/logs.
