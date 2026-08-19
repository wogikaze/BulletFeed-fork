package com.bulletfeed.app

import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.sp

@Composable
fun BulletFeedApp() {
    var events by remember { mutableStateOf(DemoData.events) }
    var tab by remember { mutableStateOf(AppTab.FEED) }
    var filter by remember { mutableStateOf(FeedFilter.ALL) }
    var selectedEvent by remember { mutableStateOf<FeedEvent?>(null) }
    var githubSetupOpen by remember { mutableStateOf(false) }
    var githubConnected by remember { mutableStateOf(false) }

    MaterialTheme(
        colorScheme = MaterialTheme.colorScheme.copy(
            primary = Color(0xFF4A2A7A), secondary = Color(0xFF006A67),
            surface = Color(0xFFFFFBFF), background = Color(0xFFFFFBFF)
        )
    ) {
        Surface(modifier = Modifier.fillMaxSize()) {
            val event = selectedEvent
            when {
                event != null -> EventDetailScreen(
                    event = event,
                    onBack = { selectedEvent = null },
                    onFeedback = { feedback ->
                        events = updateEvent(events, event.id, feedback)
                        selectedEvent = events.first { it.id == event.id }
                    },
                    onFollow = {
                        events = events.map { if (it.id == event.id) it.copy(following = !it.following) else it }
                        selectedEvent = events.first { it.id == event.id }
                    }
                )
                githubSetupOpen -> GithubConnectionScreen(
                    connected = githubConnected,
                    onBack = { githubSetupOpen = false },
                    onConnect = { githubConnected = true }
                )
                else -> Scaffold(
                    bottomBar = {
                        NavigationBar {
                            AppTab.entries.forEach { item ->
                                NavigationBarItem(
                                    selected = tab == item,
                                    onClick = { tab = item },
                                    icon = { Text(item.symbol, fontSize = 18.sp) },
                                    label = { Text(item.label) }
                                )
                            }
                        }
                    }
                ) { innerPadding ->
                    when (tab) {
                        AppTab.FEED -> FeedScreen(
                            events = events, filter = filter, onFilterChange = { filter = it },
                            onEventClick = { selectedEvent = it },
                            onFeedback = { id, feedback -> events = updateEvent(events, id, feedback) },
                            onFollow = { id -> events = events.map { if (it.id == id) it.copy(following = !it.following) else it } },
                            modifier = Modifier.padding(innerPadding)
                        )
                        AppTab.SEARCH -> SearchScreen(events, { selectedEvent = it }, Modifier.padding(innerPadding))
                        AppTab.TOPICS -> TopicsScreen(githubConnected, { githubSetupOpen = true }, Modifier.padding(innerPadding))
                        AppTab.SETTINGS -> SettingsScreen(Modifier.padding(innerPadding))
                    }
                }
            }
        }
    }
}

private fun updateEvent(events: List<FeedEvent>, id: String, feedback: Feedback) = events.map { event ->
    if (event.id != id) event else when (feedback) {
        Feedback.IMPORTANT -> event.copy(markedImportant = !event.markedImportant)
        Feedback.NOT_RELEVANT -> event.copy(read = true, dismissed = true)
        Feedback.READ -> event.copy(read = true)
    }
}

@Preview(showBackground = true, widthDp = 390, heightDp = 844)
@Composable private fun BulletFeedPreview() = BulletFeedApp()
