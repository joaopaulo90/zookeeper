#!/usr/bin/env bash
# Builds zoo-mobile's test APK (APP_ENV=test) into .build/zoo-mobile-test.apk.
#
# Built from a private copy of zoo-mobile under .build/, never in zoo-mobile
# itself: its android/ folder is generated (Expo prebuild), and regenerating
# it for a test build would clobber the dev build there. The copy keeps its
# own node_modules, reinstalled only when package-lock.json changes.
set -euo pipefail

zoo_mobile="$1"
java_home="$2"
root="$(cd "$(dirname "$0")/.." && pwd)"
copy="$root/.build/zoo-mobile"

export APP_ENV=test
export JAVA_HOME="$java_home"

mkdir -p "$copy"
rsync -a --delete \
  --exclude node_modules --exclude android --exclude ios --exclude .expo --exclude test \
  "$zoo_mobile/" "$copy/"

cd "$copy"
if ! cmp -s package-lock.json node_modules/.zookeeper-package-lock.json; then
  echo "Installing zoo-mobile's dependencies (only when package-lock.json changes)..."
  npm ci --no-audit --no-fund
  cp package-lock.json node_modules/.zookeeper-package-lock.json
fi

echo "Generating the test build's Android project..."
npx expo prebuild --platform android --clean --no-install

echo "Building the release APK (bundles the JS, so no Metro is needed)..."
(cd android && ./gradlew assembleRelease -q)

cp android/app/build/outputs/apk/release/app-release.apk "$root/.build/zoo-mobile-test.apk"
echo "Built $root/.build/zoo-mobile-test.apk"
