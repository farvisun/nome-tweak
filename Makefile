.PHONY: run test verify install uninstall package release-package translations
PYTHON = /usr/bin/python3
run:
	$(PYTHON) -m desktop_studio
test:
	$(PYTHON) -m unittest discover -s tests -v
verify:
	$(PYTHON) scripts/verify_controls.py
	$(PYTHON) scripts/verify_session.py
install:
	$(PYTHON) scripts/install.py
uninstall:
	$(PYTHON) scripts/install.py --uninstall
package: translations
	$(PYTHON) scripts/build_deb.py
translations:
	$(PYTHON) scripts/build_translations.py
release-package: translations
	$(PYTHON) scripts/build_release.py
