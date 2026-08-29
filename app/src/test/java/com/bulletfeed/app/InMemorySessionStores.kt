package com.bulletfeed.app

class InMemorySecretStore : SecretStore {
    private val values = mutableMapOf<String, String>()

    override fun get(key: String): String? = values[key]

    override fun put(
        key: String,
        value: String?,
    ) {
        if (value == null) values.remove(key) else values[key] = value
    }

    override fun remove(key: String) {
        values.remove(key)
    }

    override fun clear() {
        values.clear()
    }
}

class InMemorySessionPreferenceStore : SessionPreferenceStore {
    private val strings = mutableMapOf<String, String>()
    private val longs = mutableMapOf<String, Long>()

    override fun getString(key: String): String? = strings[key]

    override fun putString(
        key: String,
        value: String?,
    ) {
        if (value == null) strings.remove(key) else strings[key] = value
    }

    override fun getLong(
        key: String,
        default: Long,
    ): Long = longs[key] ?: default

    override fun putLong(
        key: String,
        value: Long,
    ) {
        longs[key] = value
    }

    override fun remove(key: String) {
        strings.remove(key)
        longs.remove(key)
    }

    override fun clear() {
        strings.clear()
        longs.clear()
    }
}
