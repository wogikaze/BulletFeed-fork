package com.bulletfeed.app

import android.content.Context
import android.os.Build
import com.jakewharton.retrofit2.converter.kotlinx.serialization.asConverterFactory
import kotlinx.serialization.json.Json
import okhttp3.Interceptor
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import retrofit2.Retrofit
import java.util.concurrent.TimeUnit

object BulletFeedApiFactory {
    private val json = Json {
        ignoreUnknownKeys = true
        explicitNulls = false
    }

    fun create(context: Context): Pair<BulletFeedApi, SessionManager> {
        val sessionManager = SessionManager(context)
        return create(resolveBaseUrl(), sessionManager) to sessionManager
    }

    fun create(
        baseUrl: String,
        sessionManager: SessionManager,
    ): BulletFeedApi {
        val client = OkHttpClient.Builder()
            .connectTimeout(15, TimeUnit.SECONDS)
            .readTimeout(60, TimeUnit.SECONDS)
            .addInterceptor(authInterceptor(sessionManager))
            .build()
        return Retrofit.Builder()
            .baseUrl(baseUrl)
            .client(client)
            .addConverterFactory(json.asConverterFactory("application/json".toMediaType()))
            .build()
            .create(BulletFeedApi::class.java)
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

    internal fun resolveBaseUrl(): String {
        val configured = BuildConfig.BASE_URL
        return if (!isEmulator() && configured.contains("10.0.2.2")) {
            configured.replace("10.0.2.2", "127.0.0.1")
        } else {
            configured
        }
    }

    private fun isEmulator(): Boolean {
        val fingerprint = Build.FINGERPRINT
        val model = Build.MODEL
        val product = Build.PRODUCT
        val hardware = Build.HARDWARE
        return fingerprint.startsWith("generic") ||
            fingerprint.startsWith("unknown") ||
            model.contains("google_sdk") ||
            model.contains("Emulator") ||
            model.contains("Android SDK built for") ||
            hardware.contains("goldfish") ||
            hardware.contains("ranchu") ||
            product.contains("sdk_gphone") ||
            product == "sdk" ||
            product == "google_sdk" ||
            (Build.BRAND.startsWith("generic") && Build.DEVICE.startsWith("generic"))
    }
}
