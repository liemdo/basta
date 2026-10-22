// Start a single-node replica set, then report whether it is healthy.
// Multi-document transactions require a replica set even for local Compose.
function healthy() {
  try {
    return rs.status().ok === 1;
  } catch (e) {
    return false;
  }
}

if (healthy()) {
  quit(0);
}

try {
  rs.initiate({
    _id: "rs0",
    members: [{ _id: 0, host: "mongo:27017" }],
  });
} catch (e) {
  // A previous health check may already have initiated the set.
}

quit(healthy() ? 0 : 1);
