package com.bulletfeed.app

import android.content.Context
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import retrofit2.HttpException
import java.io.IOException

data class EventSearchUiState(
    val query: String = "",
    val results: List<EventSearchItem> = emptyList(),
    val nextCursor: String? = null,
    val isLoading: Boolean = false,
    val isLoadingMore: Boolean = false,
    val errorMessage: String? = null,
)

class EventSearchViewModel(
    private val repository: EventSearchRepository,
) : ViewModel() {
    private val _uiState = MutableStateFlow(EventSearchUiState())
    val uiState: StateFlow<EventSearchUiState> = _uiState.asStateFlow()

    private var searchJob: Job? = null
    private var requestVersion = 0L

    init {
        search("")
    }

    fun search(query: String) {
        val normalized = query.trim()
        val version = ++requestVersion
        searchJob?.cancel()
        searchJob = viewModelScope.launch {
            _uiState.update {
                it.copy(
                    query = query,
                    isLoading = true,
                    isLoadingMore = false,
                    errorMessage = null,
                )
            }
            if (normalized.isNotEmpty()) delay(300)
            try {
                val page = repository.searchEvents(query = normalized)
                if (version != requestVersion) return@launch
                _uiState.update {
                    it.copy(
                        results = page.items,
                        nextCursor = page.nextCursor,
                        isLoading = false,
                        isLoadingMore = false,
                        errorMessage = null,
                    )
                }
            } catch (error: CancellationException) {
                throw error
            } catch (error: Throwable) {
                if (version != requestVersion) return@launch
                _uiState.update {
                    it.copy(
                        results = emptyList(),
                        nextCursor = null,
                        isLoading = false,
                        isLoadingMore = false,
                        errorMessage = error.toEventSearchMessage(),
                    )
                }
            }
        }
    }

    fun loadMore() {
        val state = _uiState.value
        val cursor = state.nextCursor ?: return
        if (state.isLoading || state.isLoadingMore) return
        val version = ++requestVersion
        searchJob?.cancel()
        searchJob = viewModelScope.launch {
            _uiState.update { it.copy(isLoadingMore = true, errorMessage = null) }
            try {
                val page = repository.searchEvents(
                    query = state.query.trim(),
                    cursor = cursor,
                )
                if (version != requestVersion) return@launch
                val repeatedCursor = page.nextCursor != null && page.nextCursor == cursor
                _uiState.update { current ->
                    current.copy(
                        results = mergeEventSearchResults(current.results, page.items),
                        nextCursor = if (repeatedCursor) null else page.nextCursor,
                        isLoadingMore = false,
                        errorMessage = if (repeatedCursor) {
                            "ページングcursorが進まなかったため読み込みを停止しました。"
                        } else {
                            null
                        },
                    )
                }
            } catch (error: CancellationException) {
                throw error
            } catch (error: Throwable) {
                if (version != requestVersion) return@launch
                _uiState.update {
                    it.copy(
                        isLoadingMore = false,
                        errorMessage = error.toEventSearchMessage(),
                    )
                }
            }
        }
    }

    fun retry() {
        search(_uiState.value.query)
    }

    class Factory(
        private val context: Context,
    ) : ViewModelProvider.Factory {
        @Suppress("UNCHECKED_CAST")
        override fun <T : ViewModel> create(modelClass: Class<T>): T {
            require(modelClass.isAssignableFrom(EventSearchViewModel::class.java))
            return EventSearchViewModel(
                RemoteEventSearchRepository(BulletFeedApiFactory.createEventSearch(context)),
            ) as T
        }
    }
}

internal fun mergeEventSearchResults(
    current: List<EventSearchItem>,
    incoming: List<EventSearchItem>,
): List<EventSearchItem> {
    val seen = current.mapTo(linkedSetOf()) { it.id }
    return current + incoming.filter { seen.add(it.id) }
}

private fun Throwable.toEventSearchMessage(): String =
    when {
        this is IOException -> "通信できませんでした。接続を確認して再試行してください。"
        (this as? HttpException)?.code() == 401 -> "認証の有効期限が切れました。フィードへ戻って再認証してください。"
        (this as? HttpException)?.code() == 422 -> "検索条件を処理できませんでした。入力を確認してください。"
        (this as? HttpException)?.code() == 429 -> "検索リクエストが集中しています。少し後に再試行してください。"
        ((this as? HttpException)?.code() ?: 0) >= 500 -> "検索サーバーで処理できませんでした。再試行してください。"
        else -> "検索を完了できませんでした。再試行してください。"
    }
