package com.bulletfeed.app

import android.content.Context
import com.jakewharton.retrofit2.converter.kotlinx.serialization.asConverterFactory
import kotlinx.serialization.json.Json
import okhttp3.Interceptor
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import retrofit2.Retrofit

object BulletFeedApiFactory {
    private val json = Json {
        ignoreUnknownKeys = true
        explicitNulls = false
    }

    fun create(context: Context): Pair<BulletFeedApi, SessionManager> {
        val sessionManager = SessionManager(context)
        val baseUrl = BuildConfig.BASE_URL
        val client = OkHttpClient.Builder()
            .addInterceptor(authInterceptor(sessionManager))
            .build()
        val api = Retrofit.Builder()
            .baseUrl(baseUrl)
            .client(client)
            .addConverterFactory(json.asConverterFactory("application/json".toMediaType()))
            .build()
            .create(BulletFeedApi::class.java)
        return api to sessionManager
    }

    private fun authInterceptor(sessionManager: SessionManager): Interceptor =
        Interceptor { chain ->
            val request = chain.request()
            val token = sessionManager.accessToken
            val newRequest = if (token != null && request.header("Authorization") == null) {
                request.newBuilder()
                    .header("Authorization", "Bearer $token")
                    .build()
            } else {
                request
            }
            chain.proceed(newRequest)
        }
}
