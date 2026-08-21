package com.bulletfeed.app

data class UserProfile(
    val role: String,
    val interests: Set<String>,
    val region: String,
)

data class OnboardingSnapshot(
    val completed: Boolean,
    val profile: UserProfile,
    val topics: List<String>,
)
