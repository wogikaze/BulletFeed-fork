package com.bulletfeed.app

interface SecretStore {
    fun get(key: String): String?

    fun put(
        key: String,
        value: String?,
    )

    fun remove(key: String)

    fun clear()
}
