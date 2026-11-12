#!/usr/bin/env bash
# Install, update or remove Desktop Studio, a settings app for GNOME.
#
#   Install or update:  curl -fsSL https://farvisun.github.io/nome-tweak/install.sh | bash
#   Remove:             curl -fsSL https://farvisun.github.io/nome-tweak/install.sh | bash -s -- --uninstall
#
# Desktop Studio is installed from the signed farvisun APT repository, so later
# updates arrive with your normal system updates. You will be asked for your password.
set -euo pipefail

PACKAGE="desktop-studio"
APT_SETUP="https://farvisun.github.io/apt/setup.sh"

bold=$'\033[1m'; green=$'\033[32m'; yellow=$'\033[33m'; red=$'\033[31m'; reset=$'\033[0m'
[ -t 1 ] || { bold=; green=; yellow=; red=; reset=; }
step() { printf '%s==>%s %s\n' "$bold" "$reset" "$*"; }
note() { printf '%s!%s %s\n' "$yellow" "$reset" "$*"; }
die() { printf '%serror:%s %s\n' "$red" "$reset" "$*" >&2; exit 1; }

[ "$(id -u)" -ne 0 ] || die "Run this as your normal user, not with sudo. It asks for your password when needed."
for tool in curl sudo apt-get; do
    command -v "$tool" >/dev/null 2>&1 || die "'$tool' is required but not installed."
done

if [ "${1:-}" = "--uninstall" ]; then
    step "Removing Desktop Studio"
    sudo apt-get remove -y "$PACKAGE"
    printf '%s✓%s Desktop Studio was removed. Your desktop settings, profiles and backups are kept.\n' "$green" "$reset"
    echo "  To also remove the farvisun repository: curl -fsSL $APT_SETUP | sudo bash -s -- --remove"
    exit 0
fi

step "Adding the farvisun APT repository"
curl -fsSL "$APT_SETUP" | sudo bash -s -- --quiet

was_installed=0
dpkg -s "$PACKAGE" >/dev/null 2>&1 && was_installed=1

step "Installing Desktop Studio"
sudo apt-get install -y "$PACKAGE"

# A copy installed earlier for this user only would shadow the package and add
# a second menu entry. Remove it, but only if its install marker proves it is ours.
user_app="$HOME/.local/lib/desktop-studio"
if [ -f "$user_app/.desktop-studio-install" ]; then
    rm -rf "$user_app"
    rm -f "$HOME/.local/bin/desktop-studio" \
          "$HOME/.local/share/applications/io.github.desktopstudio.DesktopStudio.desktop" \
          "$HOME/.local/share/icons/hicolor/scalable/apps/io.github.desktopstudio.DesktopStudio.svg"
    step "Replaced the copy installed for your user only. Profiles and backups are kept."
fi

echo
if [ "$was_installed" = 1 ]; then
    printf '%s✓%s Desktop Studio is updated. Restart it if it is open.\n' "$green" "$reset"
else
    printf '%s✓%s Desktop Studio is installed. Open it from the Applications menu.\n' "$green" "$reset"
fi
echo "  Updates now come with your normal system updates."
