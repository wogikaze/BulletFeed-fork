package com.bulletfeed.app

import android.content.Context

data class PendingGithubAuthorization(
    val flowId: String,
    val pollToken: String,
    val authorizationUrl: String,
    val expiresAtMillis: Long,
)

class SessionManager(
    private val secrets: SecretStore,
    private val prefs: SessionPreferenceStore,
) {
    constructor(context: Context) : this(
        KeystoreSecretStore(context),
        AndroidSessionPreferenceStore(context),
    ) {
        migrateLegacySecret(KEY_ACCESS_TOKEN)
        migrateLegacySecret(KEY_GITHUB_POLL_TOKEN)
    }

    var accessToken: String?
        get() = secrets.get(KEY_ACCESS_TOKEN)
        set(value) = secrets.put(KEY_ACCESS_TOKEN, value)

    var refreshToken: String?
        get() = secrets.get(KEY_REFRESH_TOKEN)
        set(value) = secrets.put(KEY_REFRESH_TOKEN, value)

    var userId: String?
        get() = prefs.getString(KEY_USER_ID)
        set(value) = prefs.putString(KEY_USER_ID, value)

    var pendingGithubAuthorization: PendingGithubAuthorization?
        get() {
            val flowId = prefs.getString(KEY_GITHUB_FLOW_ID) ?: return null
            val pollToken = secrets.get(KEY_GITHUB_POLL_TOKEN) ?: return null
            val authorizationUrl = prefs.getString(KEY_GITHUB_AUTH_URL) ?: return null
            val expiresAtMillis = prefs.getLong(KEY_GITHUB_EXPIRES_AT, 0L)
            return PendingGithubAuthorization(flowId, pollToken, authorizationUrl, expiresAtMillis)
        }
        set(value) {
            if (value == null) {
                prefs.remove(KEY_GITHUB_FLOW_ID)
                prefs.remove(KEY_GITHUB_AUTH_URL)
                prefs.remove(KEY_GITHUB_EXPIRES_AT)
            } else {
                prefs.putString(KEY_GITHUB_FLOW_ID, value.flowId)
                prefs.putString(KEY_GITHUB_AUTH_URL, value.authorizationUrl)
                prefs.putLong(KEY_GITHUB_EXPIRES_AT, value.expiresAtMillis)
            }
            secrets.put(KEY_GITHUB_POLL_TOKEN, value?.pollToken)
        }

    fun clearAccessToken() {
        secrets.remove(KEY_ACCESS_TOKEN)
    }

    fun clearAuthenticationTokens() {
        secrets.remove(KEY_ACCESS_TOKEN)
        secrets.remove(KEY_REFRESH_TOKEN)
        pendingGithubAuthorization = null
    }

    fun clearSession() {
        secrets.clear()
        prefs.clear()
    }

    private fun migrateLegacySecret(key: String) {
        val legacy = prefs.getString(key) ?: return
        if (secrets.get(key) == null) secrets.put(key, legacy)
        prefs.remove(key)
    }

    private companion object {
        const val KEY_ACCESS_TOKEN = "access_token"
        const val KEY_REFRESH_TOKEN = "refresh_token"
        const val KEY_USER_ID = "user_id"
        const val KEY_GITHUB_FLOW_ID = "github_flow_id"
        const val KEY_GITHUB_POLL_TOKEN = "github_poll_token"
        const val KEY_GITHUB_AUTH_URL = "github_auth_url"
        const val KEY_GITHUB_EXPIRES_AT = "github_expires_at"
    }
}
