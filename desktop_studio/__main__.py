import sys

if "--check-updates" in sys.argv:
    import argparse
    import json
    from .platform.updates import UpdateChecker
    from .core.settings import SettingsError
    parser = argparse.ArgumentParser(description="Check stable Desktop Studio releases without changing desktop settings")
    parser.add_argument("--check-updates", action="store_true")
    parser.add_argument("--repository", help="Check owner/repository without saving an override")
    args = parser.parse_args()
    try:
        result = UpdateChecker().check(repository=args.repository)
        print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
        raise SystemExit(0 if result.status in ("available", "up-to-date") else 2)
    except (OSError, ValueError, SettingsError) as exc:
        print(json.dumps({"status": "error", "message": str(exc)}))
        raise SystemExit(2)
elif "--diagnose" in sys.argv:
    import json
    from .core.settings import Registry
    from .platform.services import Environment
    from .diagnostics import report
    print(json.dumps(report(Registry(), Environment()), indent=2, ensure_ascii=False))
else:
    from .app import main
    raise SystemExit(main())
