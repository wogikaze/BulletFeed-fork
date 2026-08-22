# Maestro UI flows

These flows exercise the installed `com.bulletfeed.app` APK through the Android accessibility layer.

Install Maestro using the official installer, connect an emulator or a USB-debuggable device, install the debug APK, then run:

```bash
maestro test maestro/flows/onboarding.yaml
maestro test maestro/flows/feed.yaml
maestro test maestro/flows/filter.yaml
maestro test maestro/flows/notifications.yaml
maestro test maestro/flows/security.yaml
```

The flows use `clearState: true` so each scenario starts with the Mock Repository's initial state. They are black-box tests and do not require Android instrumentation dependencies.
