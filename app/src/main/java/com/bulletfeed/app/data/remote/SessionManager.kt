package com.bulletfeed.app

import android.content.Context
import androidx.core.content.edit

data class PendingGithubAuthorization(
    val flowId: String,
    val pollToken: String,
    val authorizationUrl: String,
    val expiresAtMillis: Long,
)

class SessionManager(
    context: Context,
) {
    private val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
    private val secrets = KeystoreSecretStore(context)

    init {
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
        get() = prefs.getString(KEY_USER_ID, null)
        set(value) = prefs.edit { putString(KEY_USER_ID, value) }

    var pendingGithubAuthorization: PendingGithubAuthorization?
        get() {
            val flowId = prefs.getString(KEY_GITHUB_FLOW_ID, null) ?: return null
            val pollToken = secrets.get(KEY_GITHUB_POLL_TOKEN) ?: return null
            val authorizationUrl = prefs.getString(KEY_GITHUB_AUTH_URL, null) ?: return null
            val expiresAtMillis = prefs.getLong(KEY_GITHUB_EXPIRES_AT, 0L)
            return PendingGithubAuthorization(flowId, pollToken, authorizationUrl, expiresAtMillis)
        }
        set(value) {
            prefs.edit {
                if (value == null) {
                    remove(KEY_GITHUB_FLOW_ID)
                    remove(KEY_GITHUB_AUTH_URL)
                    remove(KEY_GITHUB_EXPIRES_AT)
                } else {
                    putString(KEY_GITHUB_FLOW_ID, value.flowId)
                    putString(KEY_GITHUB_AUTH_URL, value.authorizationUrl)
                    putLong(KEY_GITHUB_EXPIRES_AT, value.expiresAtMillis)
                }
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
        prefs.edit { clear() }
    }

    private fun migrateLegacySecret(key: String) {
        val legacy = prefs.getString(key, null) ?: return
        if (secrets.get(key) == null) secrets.put(key, legacy)
        prefs.edit { remove(key) }
    }

    companion object {
        private const val PREFS_NAME = "bulletfeed_session"
        private const val KEY_ACCESS_TOKEN = "access_token"
        private const val KEY_REFRESH_TOKEN = "refresh_token"
        private const val KEY_USER_ID = "user_id"
        private const val KEY_GITHUB_FLOW_ID = "github_flow_id"
        private const val KEY_GITHUB_POLL_TOKEN = "github_poll_token"
        private const val KEY_GITHUB_AUTH_URL = "github_auth_url"
        private const val KEY_GITHUB_EXPIRES_AT = "github_expires_at"
    }
}
