package com.bulletfeed.app

import android.content.Context
import androidx.core.content.edit

interface SessionPreferenceStore {
    fun getString(key: String): String?

    fun putString(
        key: String,
        value: String?,
    )

    fun getLong(
        key: String,
        default: Long = 0L,
    ): Long

    fun putLong(
        key: String,
        value: Long,
    )

    fun remove(key: String)

    fun clear()
}

internal class AndroidSessionPreferenceStore(
    context: Context,
) : SessionPreferenceStore {
    private val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)

    override fun getString(key: String): String? = prefs.getString(key, null)

    override fun putString(
        key: String,
        value: String?,
    ) {
        prefs.edit {
            if (value == null) remove(key) else putString(key, value)
        }
    }

    override fun getLong(
        key: String,
        default: Long,
    ): Long = prefs.getLong(key, default)

    override fun putLong(
        key: String,
        value: Long,
    ) {
        prefs.edit { putLong(key, value) }
    }

    override fun remove(key: String) {
        prefs.edit { remove(key) }
    }

    override fun clear() {
        prefs.edit { clear() }
    }

    private companion object {
        const val PREFS_NAME = "bulletfeed_session"
    }
}
