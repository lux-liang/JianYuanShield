package com.vpsg.jianyuanshield.core

/** Join a backend base URL with a relative artifact path returned by the API. */
fun absoluteArtifactUrl(base: String, path: String): String {
    // Absolute URLs and local URIs (demo mode serves the picked image) pass through.
    if (
        path.startsWith("http://") || path.startsWith("https://") ||
        path.startsWith("content://") || path.startsWith("file://")
    ) {
        return path
    }
    if (base.isBlank()) return path
    return base.trimEnd('/') + "/" + path.trimStart('/')
}
