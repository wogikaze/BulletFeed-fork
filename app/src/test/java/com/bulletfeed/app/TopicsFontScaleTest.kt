package com.bulletfeed.app

import androidx.compose.foundation.layout.Column
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.test.assertHeightIsAtLeast
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.unit.Density
import androidx.compose.ui.unit.dp
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.GraphicsMode

@RunWith(RobolectricTestRunner::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
class TopicsFontScaleTest {
    @get:Rule
    val composeRule = createComposeRule()

    @Test
    fun largeFontScaleKeepsRecommendationSearchAndAddTouchTargets() {
        composeRule.setContent {
            MaterialTheme {
                CompositionLocalProvider(
                    LocalDensity provides Density(density = 1f, fontScale = AppReadability.LARGE_FONT_SCALE),
                ) {
                    Column {
                        TopicRecommendationActions(enabled = true, onAdd = {}, onIgnore = {})
                        TopicSearchBar(
                            query = "React",
                            onQueryChange = {},
                            isSearching = false,
                            onSearch = {},
                        )
                        TopicTypeFilterRow(selectedType = TopicType.TECHNOLOGY, onTypeSelected = {})
                        TopicFreeformAddBar(
                            value = "Kotlin",
                            onValueChange = {},
                            enabled = true,
                            onAdd = {},
                        )
                        TopicGithubConnectButton(githubConnected = false, onClick = {})
                    }
                }
            }
        }

        composeRule.onNodeWithTag("topic-recommendation-add").assertHeightIsAtLeast(48.dp)
        composeRule.onNodeWithTag("topic-recommendation-ignore").assertHeightIsAtLeast(48.dp)
        composeRule.onNodeWithText("無視").assertHeightIsAtLeast(48.dp)
        composeRule.onNodeWithTag("topic-search-field", useUnmergedTree = true).assertHeightIsAtLeast(48.dp)
        composeRule.onNodeWithTag("topic-search-button").assertHeightIsAtLeast(48.dp)
        composeRule.onNodeWithText("検索").assertHeightIsAtLeast(48.dp)
        composeRule.onNodeWithTag("topic-type-technology").assertHeightIsAtLeast(48.dp)
        composeRule.onNodeWithText("技術").assertHeightIsAtLeast(48.dp)
        composeRule.onNodeWithTag("topic-add-field", useUnmergedTree = true).assertHeightIsAtLeast(48.dp)
        composeRule.onNodeWithTag("topic-add-button").assertHeightIsAtLeast(48.dp)
        composeRule.onNodeWithContentDescription("追加").assertHeightIsAtLeast(48.dp)
        composeRule.onNodeWithTag("topic-github-connect").assertHeightIsAtLeast(48.dp)
        composeRule.onNodeWithText("GitHubを連携する").assertHeightIsAtLeast(48.dp)
    }

    @Test
    fun largeFontScaleKeepsTrackedTopicPriorityAndRemoveTouchTargets() {
        composeRule.setContent {
            MaterialTheme {
                CompositionLocalProvider(
                    LocalDensity provides Density(density = 1f, fontScale = AppReadability.LARGE_FONT_SCALE),
                ) {
                    TopicManagementCard(
                        topic = UserTopic(
                            id = "topic-1",
                            name = "React",
                            type = TopicType.TECHNOLOGY,
                            priority = TopicPriority.HIGH,
                            order = 0,
                        ),
                        dragging = false,
                        dragHandleModifier = Modifier,
                        onPriorityChange = { _, _ -> },
                        onRemoveTopic = {},
                    )
                }
            }
        }

        composeRule.onNodeWithTag("topic-reorder").assertHeightIsAtLeast(48.dp)
        composeRule.onNodeWithContentDescription("並び替え").assertHeightIsAtLeast(48.dp)
        composeRule.onNodeWithTag("topic-priority").assertHeightIsAtLeast(48.dp)
        composeRule.onNodeWithText("高").assertHeightIsAtLeast(48.dp)
        composeRule.onNodeWithTag("topic-remove").assertHeightIsAtLeast(48.dp)
        composeRule.onNodeWithText("削除").assertHeightIsAtLeast(48.dp)
    }
}
