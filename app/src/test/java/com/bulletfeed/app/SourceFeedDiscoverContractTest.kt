package com.bulletfeed.app

import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class SourceFeedDiscoverContractTest {
    @Test
    fun mockDiscoverReturnsCandidatesWithoutCreatingSubscriptions() =
        runTest {
            val repository = MockBulletFeedRepository()
            val before = repository.getSourceSubscriptions()
            val discovered = repository.discoverSiteFeeds("https://notes.example.com/")

            assertEquals("site-feed-discover-v1", discovered.version)
            assertEquals("rss_atom", discovered.preferredFamily)
            assertTrue(discovered.items.isNotEmpty())
            assertTrue(discovered.items.all { it.discoveryOnly })
            assertTrue(discovered.items.all { !it.evidenceEligible })
            assertTrue(discovered.items.any { it.preferred && it.family == "rss_atom" })
            assertEquals(before, repository.getSourceSubscriptions())
        }
}
