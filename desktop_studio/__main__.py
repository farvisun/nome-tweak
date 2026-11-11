import sys

if "--diagnose" in sys.argv:
    import json
    from .core.settings import Registry
    from .platform.services import Environment
    from .diagnostics import report
    print(json.dumps(report(Registry(), Environment()), indent=2, ensure_ascii=False))
else:
    from .app import main
    raise SystemExit(main())
