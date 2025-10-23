#!/usr/bin/env bash
set -e

# Ensure timezone is applied for the session (overrideable via -e TZ=...)
: ${TZ:=Asia/Tokyo}
export TZ
if [ -f /etc/timezone ] && [ "$(cat /etc/timezone)" != "$TZ" ]; then
  ln -snf /usr/share/zoneinfo/$TZ /etc/localtime || true
  echo $TZ > /etc/timezone || true
fi

# Allow the container to run processes as the host user to avoid root-owned files on bind mounts
: ${LOCAL_UID:=1000}
: ${LOCAL_GID:=1000}
: ${LOCAL_USER:=app}
: ${LOCAL_GROUP:=app}

# Ensure group exists
if ! getent group ${LOCAL_GID} >/dev/null 2>&1; then
  if getent group ${LOCAL_GROUP} >/dev/null 2>&1; then
    groupmod -g ${LOCAL_GID} ${LOCAL_GROUP} || true
  else
    groupadd -g ${LOCAL_GID} ${LOCAL_GROUP}
  fi
fi

# Ensure user exists with given UID/GID
if ! id -u ${LOCAL_UID} >/dev/null 2>&1; then
  useradd -m -u ${LOCAL_UID} -g ${LOCAL_GID} -s /bin/bash ${LOCAL_USER}
else
  # If UID exists under a different name, ensure it's in the right group
  usermod -g ${LOCAL_GID} $(getent passwd ${LOCAL_UID} | cut -d: -f1) || true
fi

# Ensure workspace ownership is writable by group
mkdir -p /workspace
chgrp -R ${LOCAL_GID} /workspace || true
chmod -R g+rwX /workspace || true

# Favor group-writable files by default
umask 0002

# Exec the requested command as the specified user
if [ -n "${LOCAL_USER}" ] && id -u ${LOCAL_UID} >/dev/null 2>&1; then
  exec gosu ${LOCAL_UID}:${LOCAL_GID} "$@"
else
  exec "$@"
fi
