#!/usr/bin/env bash
set -euo pipefail
umask 022

readonly DEFAULT_PUBLIC_ROOT="/opt/JianYuanShield"
readonly REQUIRED_FRONTEND_FILES=(
  "index.html"
  "app.js"
  "styles.css"
  "trust-contracts.js"
)

SOURCE_ROOT="${SOURCE_ROOT:-}"
RELEASE_ID="${RELEASE_ID:-}"
PUBLIC_ROOT="${PUBLIC_ROOT:-$DEFAULT_PUBLIC_ROOT}"
PUBLIC_OWNER="${PUBLIC_OWNER:-}"
MODELS_STATUS_FILE="${MODELS_STATUS_FILE:-}"
REQUIRE_MODELS_STATUS="${REQUIRE_MODELS_STATUS:-false}"
LARGE_PNG_BYTES="${LARGE_PNG_BYTES:-1048576}"
ROLLBACK_ID=""

usage() {
  cat <<'EOF'
Usage:
  deploy-public-release.sh --source-root ABS_PATH --release-id ID
  deploy-public-release.sh ABS_SOURCE_ROOT RELEASE_ID
  deploy-public-release.sh --rollback ID

SOURCE_ROOT, RELEASE_ID and PUBLIC_ROOT may also be supplied as environment
variables. PUBLIC_ROOT defaults to /opt/JianYuanShield. A repository-local
system/edge-api/models-status.json is copied when present. Set
MODELS_STATUS_FILE to select another snapshot, or REQUIRE_MODELS_STATUS=true
to fail when no snapshot is available.

The script only creates immutable, root-owned release directories and
atomically changes the current symlink. PUBLIC_OWNER defaults to root:caddy;
the release directories are mode 0555 and files are mode 0444 so Caddy has
read-only access. It never removes completed releases or reloads Caddy.
EOF
}

die() {
  printf 'deploy-public-release: %s\n' "$*" >&2
  exit 1
}

validate_release_id() {
  local candidate="$1"
  [[ "$candidate" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$ ]] ||
    die "unsafe release id: use 1-128 ASCII letters, digits, dots, underscores or hyphens"
  [[ "$candidate" != "." && "$candidate" != ".." && "$candidate" != *".."* ]] ||
    die "unsafe release id: '..' is not allowed"
}

require_absolute_path() {
  local label="$1"
  local candidate="$2"
  [[ "$candidate" == /* ]] || die "$label must be an absolute path"
  [[ "$candidate" != *$'\n'* && "$candidate" != *$'\r'* ]] ||
    die "$label contains a line break"
}

assert_release_target() {
  local candidate="$1"
  local expected="$2"
  [[ "$candidate" == "$expected" ]] || die "release target did not resolve to its expected path"
  case "$candidate" in
    "$RELEASES_ROOT"/*) ;;
    *) die "release target escapes $RELEASES_ROOT" ;;
  esac
}

POSITIONAL=()
while (($# > 0)); do
  case "$1" in
    --source-root)
      (($# >= 2)) || die "--source-root requires a value"
      SOURCE_ROOT="$2"
      shift 2
      ;;
    --release-id)
      (($# >= 2)) || die "--release-id requires a value"
      RELEASE_ID="$2"
      shift 2
      ;;
    --public-root)
      (($# >= 2)) || die "--public-root requires a value"
      PUBLIC_ROOT="$2"
      shift 2
      ;;
    --rollback)
      (($# >= 2)) || die "--rollback requires a release id"
      ROLLBACK_ID="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    --)
      shift
      while (($# > 0)); do
        POSITIONAL+=("$1")
        shift
      done
      ;;
    -*)
      die "unknown option: $1"
      ;;
    *)
      POSITIONAL+=("$1")
      shift
      ;;
  esac
done

if ((${#POSITIONAL[@]} > 0)); then
  ((${#POSITIONAL[@]} == 2)) || die "deployment expects SOURCE_ROOT and RELEASE_ID"
  [[ -z "$SOURCE_ROOT" && -z "$RELEASE_ID" ]] ||
    die "do not mix positional source/release values with flags or environment variables"
  SOURCE_ROOT="${POSITIONAL[0]}"
  RELEASE_ID="${POSITIONAL[1]}"
fi

[[ "$REQUIRE_MODELS_STATUS" == "true" || "$REQUIRE_MODELS_STATUS" == "false" ]] ||
  die "REQUIRE_MODELS_STATUS must be true or false"
[[ "$LARGE_PNG_BYTES" =~ ^[0-9]+$ ]] || die "LARGE_PNG_BYTES must be a non-negative integer"

require_absolute_path "PUBLIC_ROOT" "$PUBLIC_ROOT"
PUBLIC_ROOT="$(realpath -m -- "$PUBLIC_ROOT")"
[[ "$PUBLIC_ROOT" != "/" ]] || die "PUBLIC_ROOT must not be the filesystem root"

RELEASES_ROOT="$(realpath -m -- "$PUBLIC_ROOT/releases")"
[[ "$RELEASES_ROOT" == "$PUBLIC_ROOT/releases" ]] ||
  die "release directory did not resolve beneath PUBLIC_ROOT"

CURRENT_LINK_TEMP=""
cleanup_current_link_temp() {
  if [[ -n "$CURRENT_LINK_TEMP" && "$CURRENT_LINK_TEMP" == "$PUBLIC_ROOT/.current-link."*".tmp" ]]; then
    if [[ -L "$CURRENT_LINK_TEMP" || -f "$CURRENT_LINK_TEMP" ]]; then
      rm -f -- "$CURRENT_LINK_TEMP"
    fi
  fi
}

switch_current() {
  local target_id="$1"
  local target_release="$RELEASES_ROOT/$target_id"
  local owner_user="${PUBLIC_OWNER%%:*}"
  local owner_group="${PUBLIC_OWNER#*:}"

  validate_release_id "$target_id"
  target_release="$(realpath -m -- "$target_release")"
  assert_release_target "$target_release" "$RELEASES_ROOT/$target_id"
  [[ -d "$target_release" && ! -L "$target_release" ]] ||
    die "release does not exist: $target_id"
  [[ -z "$(find -P "$target_release" -type l -print -quit)" ]] ||
    die "release $target_id contains a symbolic link"
  [[ -z "$(find -P "$target_release" \( -type d -o -type f \) -perm /0222 -print -quit)" ]] ||
    die "release $target_id contains writable content"
  [[ -z "$(find -P "$target_release" \( -type d -o -type f \) \( ! -user "$owner_user" -o ! -group "$owner_group" \) -print -quit)" ]] ||
    die "release $target_id has unexpected ownership"
  for required in "${REQUIRED_FRONTEND_FILES[@]}"; do
    [[ -f "$target_release/system/frontend/$required" && ! -L "$target_release/system/frontend/$required" ]] ||
      die "release $target_id is missing system/frontend/$required"
  done
  [[ -f "$target_release/RELEASE-MANIFEST.sha256" && ! -L "$target_release/RELEASE-MANIFEST.sha256" ]] ||
    die "release $target_id has no checksum manifest"
  (
    cd "$target_release"
    sha256sum --check --strict RELEASE-MANIFEST.sha256 >/dev/null
  ) || die "release $target_id failed checksum verification"

  CURRENT_LINK_TEMP="$PUBLIC_ROOT/.current-link.$$.tmp"
  [[ ! -e "$CURRENT_LINK_TEMP" && ! -L "$CURRENT_LINK_TEMP" ]] ||
    die "temporary current link already exists"
  ln -sfnT -- "releases/$target_id" "$CURRENT_LINK_TEMP"
  chown -h -- "$PUBLIC_OWNER" "$CURRENT_LINK_TEMP"
  mv -Tf -- "$CURRENT_LINK_TEMP" "$PUBLIC_ROOT/current"
  CURRENT_LINK_TEMP=""
}

if [[ -z "$PUBLIC_OWNER" ]]; then
  if [[ "$PUBLIC_ROOT" == "$DEFAULT_PUBLIC_ROOT" ]]; then
    PUBLIC_OWNER="root:caddy"
  else
    PUBLIC_OWNER="$(id -u):$(id -g)"
  fi
fi
[[ "$PUBLIC_OWNER" =~ ^[A-Za-z0-9_.-]+:[A-Za-z0-9_.-]+$ ]] ||
  die "PUBLIC_OWNER must be in user:group form"

# The parent paths remain writable only by their owner. The Caddy group can
# traverse them, but cannot create, replace or delete a release or symlink.
install -d -m 0755 -- "$PUBLIC_ROOT" "$RELEASES_ROOT"
chown -- "$PUBLIC_OWNER" "$PUBLIC_ROOT" "$RELEASES_ROOT"
chmod 0755 -- "$PUBLIC_ROOT" "$RELEASES_ROOT"

trap cleanup_current_link_temp EXIT

if [[ -n "$ROLLBACK_ID" ]]; then
  [[ -z "$SOURCE_ROOT" && -z "$RELEASE_ID" ]] ||
    die "rollback cannot be combined with a source or release id"
  switch_current "$ROLLBACK_ID"
  printf 'Rolled back current to release %s\n' "$ROLLBACK_ID"
  exit 0
fi

[[ -n "$SOURCE_ROOT" ]] || die "SOURCE_ROOT is required"
[[ -n "$RELEASE_ID" ]] || die "RELEASE_ID is required"
validate_release_id "$RELEASE_ID"
require_absolute_path "SOURCE_ROOT" "$SOURCE_ROOT"
[[ -d "$SOURCE_ROOT" && ! -L "$SOURCE_ROOT" ]] || die "SOURCE_ROOT must be an existing directory, not a symlink"
SOURCE_ROOT="$(realpath -e -- "$SOURCE_ROOT")"

FRONTEND_SOURCE="$SOURCE_ROOT/system/frontend"
[[ -d "$FRONTEND_SOURCE" && ! -L "$FRONTEND_SOURCE" ]] ||
  die "SOURCE_ROOT must contain a real system/frontend directory"
for required in "${REQUIRED_FRONTEND_FILES[@]}"; do
  [[ -f "$FRONTEND_SOURCE/$required" && ! -L "$FRONTEND_SOURCE/$required" ]] ||
    die "source is missing system/frontend/$required"
done

# Reject links and special files anywhere below the public source. Filtering
# only regular files is insufficient because it would silently ignore a link
# that a later copy or operator might follow.
SOURCE_LINK="$(find -P "$FRONTEND_SOURCE" -type l -print -quit)" ||
  die "could not scan frontend source for symbolic links"
[[ -z "$SOURCE_LINK" ]] || die "frontend source contains a symbolic link"
SOURCE_SPECIAL="$(find -P "$FRONTEND_SOURCE" ! -type d ! -type f -print -quit)" ||
  die "could not scan frontend source for special files"
[[ -z "$SOURCE_SPECIAL" ]] || die "frontend source contains a non-regular file"

if [[ -n "$MODELS_STATUS_FILE" ]]; then
  require_absolute_path "MODELS_STATUS_FILE" "$MODELS_STATUS_FILE"
  [[ -f "$MODELS_STATUS_FILE" && ! -L "$MODELS_STATUS_FILE" ]] ||
    die "MODELS_STATUS_FILE must be an existing regular file, not a symlink"
  MODELS_STATUS_FILE="$(realpath -e -- "$MODELS_STATUS_FILE")"
elif [[ -f "$SOURCE_ROOT/system/edge-api/models-status.json" && ! -L "$SOURCE_ROOT/system/edge-api/models-status.json" ]]; then
  MODELS_STATUS_FILE="$SOURCE_ROOT/system/edge-api/models-status.json"
elif [[ "$REQUIRE_MODELS_STATUS" == "true" ]]; then
  die "models-status.json is required but was not found"
fi

RELEASE_DIR="$(realpath -m -- "$RELEASES_ROOT/$RELEASE_ID")"
STAGING_DIR="$(realpath -m -- "$RELEASES_ROOT/$RELEASE_ID.staging")"
assert_release_target "$RELEASE_DIR" "$RELEASES_ROOT/$RELEASE_ID"
assert_release_target "$STAGING_DIR" "$RELEASES_ROOT/$RELEASE_ID.staging"
[[ ! -e "$RELEASE_DIR" && ! -L "$RELEASE_DIR" ]] || die "release already exists: $RELEASE_ID"
[[ ! -e "$STAGING_DIR" && ! -L "$STAGING_DIR" ]] ||
  die "staging directory already exists; inspect it before retrying: $STAGING_DIR"

STAGING_OWNED="false"
cleanup_staging() {
  if [[ "$STAGING_OWNED" == "true" && "$STAGING_DIR" == "$RELEASES_ROOT/$RELEASE_ID.staging" ]]; then
    case "$STAGING_DIR" in
      "$RELEASES_ROOT"/*)
        if [[ -d "$STAGING_DIR" && ! -L "$STAGING_DIR" ]]; then
          # A failure after sealing may leave the owned staging tree read-only.
          # Re-enable owner permissions only on the exact validated staging
          # path so cleanup remains reliable without touching any release.
          find -P "$STAGING_DIR" -type d -exec chmod u+rwx {} + || true
          find -P "$STAGING_DIR" -type f -exec chmod u+rw {} + || true
          rm -rf -- "$STAGING_DIR"
        fi
        ;;
    esac
  fi
  cleanup_current_link_temp
}
trap cleanup_staging EXIT

is_private_frontend_path() {
  local relative="${1,,}"
  local wrapped="/$relative/"
  local basename="${relative##*/}"

  # No dotfile or dot-directory is needed by the browser release. This also
  # excludes .git and every .env variant at any nesting depth.
  case "$wrapped" in
    */.*/*) return 0 ;;
  esac

  # Exclude conventional secret stores and backup directories at every depth.
  case "$wrapped" in
    */backup/*|*/backups/*|*/credential/*|*/credentials/*|*/password/*|*/passwords/*|*/token/*|*/tokens/*|*/secret/*|*/secrets/*|*/key/*|*/keys/*|*/key-material/*|*/key-materials/*|*/key_material/*|*/key_materials/*|*/private-key/*|*/private-keys/*|*/private_key/*|*/private_keys/*)
      return 0
      ;;
  esac

  # Filenames that advertise credentials or private key material are never
  # suitable public assets, irrespective of their extension.
  case "$basename" in
    *credential*|*password*|*secret*|*token*|private-key*|private_key*|id_rsa*|id_ed25519*|authorized_keys|known_hosts)
      return 0
      ;;
    *.pem|*.key|*.p12|*.pfx|*.pkcs8|*.jks|*.keystore|*.der|*.pub)
      return 0
      ;;
    *.bak|*.bak-*|*.bak.*|*.orig|*.tmp|*.swp|*.swo|*~|*.map|*.psd|*.ai|*.xcf|*.sketch|*.blend|thumbs.db|.ds_store)
      return 0
      ;;
  esac

  return 1
}

is_allowed_frontend_path() {
  local basename="${1##*/}"
  local lower_basename="${basename,,}"

  # Positive allowlist: an unexpected database, archive, executable or other
  # file type cannot become public merely because its name was unfamiliar.
  case "$lower_basename" in
    *.html|*.css|*.js|*.mjs|*.json|*.webmanifest|*.svg|*.png|*.webp|*.jpg|*.jpeg|*.gif|*.avif|*.ico|*.woff|*.woff2|*.ttf|*.otf|*.md|*.txt)
      return 0
      ;;
  esac
  return 1
}

# Inventory and classify the complete tree before copying any byte. A file
# that is not explicitly public is ignored; links and special files were
# rejected above, so an incomplete scan cannot silently produce a release.
declare -a PUBLIC_SOURCE_FILES=()
while IFS= read -r -d '' source_file; do
  relative="${source_file#"$FRONTEND_SOURCE/"}"
  [[ "$relative" != "$source_file" ]] || die "frontend file escaped its source root"
  [[ "$relative" != *$'\n'* && "$relative" != *$'\r'* ]] ||
    die "frontend path contains a line break"
  lower_relative="${relative,,}"
  is_private_frontend_path "$relative" && continue
  is_allowed_frontend_path "$relative" || continue

  [[ -f "$source_file" && ! -L "$source_file" ]] ||
    die "frontend source changed during deployment"

  if [[ "$lower_relative" == *.png ]]; then
    png_size="$(stat -c '%s' -- "$source_file")"
    png_base="${source_file%.*}"
    if ((png_size > LARGE_PNG_BYTES)) &&
       { [[ -f "$png_base.webp" && ! -L "$png_base.webp" ]] ||
         [[ -f "$png_base.WEBP" && ! -L "$png_base.WEBP" ]]; }; then
      continue
    fi
  fi

  PUBLIC_SOURCE_FILES+=("$source_file")
done < <(find -P "$FRONTEND_SOURCE" -type f -print0)

install -d -m 0755 -- "$STAGING_DIR/system/frontend"
STAGING_OWNED="true"

for source_file in "${PUBLIC_SOURCE_FILES[@]}"; do
  relative="${source_file#"$FRONTEND_SOURCE/"}"
  [[ -f "$source_file" && ! -L "$source_file" ]] ||
    die "frontend source changed during deployment"
  install -D -m 0644 -- "$source_file" "$STAGING_DIR/system/frontend/$relative"
done

if [[ -n "$MODELS_STATUS_FILE" ]]; then
  install -D -m 0644 -- "$MODELS_STATUS_FILE" "$STAGING_DIR/system/edge-api/models-status.json"
fi

cat >"$STAGING_DIR/RELEASE-METADATA" <<EOF
release_id=$RELEASE_ID
created_at=$(date -u +'%Y-%m-%dT%H:%M:%SZ')
models_status=$([[ -n "$MODELS_STATUS_FILE" ]] && printf 'included' || printf 'absent')
EOF

find -P "$STAGING_DIR" -type d -exec chmod 0755 {} +
find -P "$STAGING_DIR" -type f -exec chmod 0644 {} +

(
  cd "$STAGING_DIR"
  while IFS= read -r -d '' relative; do
    sha256sum -- "$relative"
  done < <(
    { find system -type f -print0; printf '%s\0' 'RELEASE-METADATA'; } | sort -z
  )
) >"$STAGING_DIR/RELEASE-MANIFEST.sha256"
chmod 0644 -- "$STAGING_DIR/RELEASE-MANIFEST.sha256"

chown -R -- "$PUBLIC_OWNER" "$STAGING_DIR"
(
  cd "$STAGING_DIR"
  sha256sum --check --strict RELEASE-MANIFEST.sha256 >/dev/null
)

# Seal the complete tree only after every byte has been checksummed. The
# owner can still remove a release through its parent when intentionally
# performing maintenance, while neither Caddy nor the owner can mutate files
# in place accidentally.
find -P "$STAGING_DIR" -type d -exec chmod 0555 {} +
find -P "$STAGING_DIR" -type f -exec chmod 0444 {} +

mv -- "$STAGING_DIR" "$RELEASE_DIR"
STAGING_OWNED="false"
switch_current "$RELEASE_ID"

printf 'Published release %s at %s\n' "$RELEASE_ID" "$RELEASE_DIR"
