package com.bulletfeed.app

import kotlinx.serialization.Serializable
import retrofit2.http.GET
import retrofit2.http.Query

interface EventSearchApi {
    @GET("v1/events/search")
    suspend fun searchEvents(
        @Query("q") query: String = "",
        @Query("cursor") cursor: String? = null,
        @Query("limit") limit: Int = 20,
    ): EventSearchPageDto
}

@Serializable
data class EventSearchPageDto(
    val items: List<EventSearchItemDto>,
    val nextCursor: String? = null,
)

@Serializable
data class EventSearchItemDto(
    val id: String,
    val title: String,
    val summary: String,
    val currentPhase: String,
    val currentSummary: String,
    val updatedAt: String,
    val following: Boolean,
    val sourcePublisher: String? = null,
)

data class EventSearchItem(
    val id: String,
    val title: String,
    val summary: String,
    val currentPhase: String,
    val currentSummary: String,
    val updatedAt: String,
    val following: Boolean,
    val sourcePublisher: String?,
)

data class EventSearchPage(
    val items: List<EventSearchItem>,
    val nextCursor: String?,
)

interface EventSearchRepository {
    suspend fun searchEvents(
        query: String = "",
        cursor: String? = null,
        limit: Int = 20,
    ): EventSearchPage
}

class RemoteEventSearchRepository(
    private val api: EventSearchApi,
) : EventSearchRepository {
    override suspend fun searchEvents(
        query: String,
        cursor: String?,
        limit: Int,
    ): EventSearchPage = api.searchEvents(query = query, cursor = cursor, limit = limit).toDomain()
}

private fun EventSearchPageDto.toDomain(): EventSearchPage =
    EventSearchPage(items = items.map { it.toDomain() }, nextCursor = nextCursor)

private fun EventSearchItemDto.toDomain(): EventSearchItem =
    EventSearchItem(
        id = id,
        title = title,
        summary = summary,
        currentPhase = currentPhase,
        currentSummary = currentSummary,
        updatedAt = updatedAt,
        following = following,
        sourcePublisher = sourcePublisher,
    )
