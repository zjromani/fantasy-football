# Owner → GM UX Transformation

## Summary of Changes

This document outlines the surgical UX changes made to transform the Fantasy Football AI app from a "GM activity log" to an **Owner-first decision inbox**.

---

## ✅ Completed Changes

### 1. **Owner Inbox** (formerly "Awaiting Your Decision")
- **Changed:** Main section title from "Awaiting Your Decision" → **"Owner Inbox"**
- **Added:** "Owner Mode" description banner with GM attribution
- **Visual:** Larger, bolder heading (text-3xl) with inbox icon
- **Copy:** "Your AI GM has analyzed the latest data and prepared X recommendations for your approval"

**Impact:** Immediately shifts mental model from "reviewing audit logs" to "making owner decisions"

### 2. **GM Attribution on Every Card**
- **Added:** "GM Recommends" badge at top of each action card
- **Changed:** Button labels: "Approve" → **"Accept"**, "Deny" → **"Decline"**
- **Enhanced:** "Why?" button (formerly info icon) with "See receipts" tooltip
- **Toast messages:** Updated to "GM recommendation accepted • Undo"

**Impact:** Reinforces Owner/GM role separation and makes AI assistance explicit

### 3. **Coach Bar Enhancements**
- **Changed:** CTA text from "X Actions" → **"X Decisions"**
- **Added:** ⌘K hint on hover (for future command palette)
- **TODO markers:** Staleness indicators, win probability, lineup risk

**Impact:** More owner-centric language, better status communication

### 4. **Demoted Activity Feed**
- **Changed:** "Activity Feed" → **"Recent Activity"**
- **Visual:** Reduced heading size (text-xl → text-lg), lighter color (text-slate-700)
- **Spacing:** Increased margin-top (mt-8 → mt-12) to separate from primary inbox

**Impact:** Makes historical log secondary to decision surface

### 5. **Accessibility Improvements**
- **Added:** `aria-label` on Accept/Decline buttons
- **Added:** Mobile-responsive Decline button (icon on mobile, text on desktop)
- **Foundation:** Keyboard shortcut comments (A = Accept, D = Decline)

**Impact:** Better for screen readers and keyboard navigation

### 6. **Keyboard Shortcuts**
- **Added:** Press `A` to accept first visible recommendation
- **Added:** Press `D` to decline first visible recommendation
- **Smart:** Skips when typing in input fields, only works on visible cards

**Impact:** Power users can process decisions at keyboard speed

### 7. **Batch Actions**
- **Added:** "Accept All (X)" button when multiple recommendations present
- **Sequential processing:** Accepts each recommendation one by one
- **Feedback:** Shows progress and handles partial failures gracefully

**Impact:** One-click to accept all GM recommendations when confident

### 8. **TODO Markers for Next Phase**
- Command Palette (⌘K)
- Player Drawer (slide-over with news/projections)
- Auto-Loop toggles (scheduled auto-runs)
- Data freshness badges (needs backend timestamp)
- Projected delta badges (needs backend calculation)
- Weekly cadence banner

**Impact:** Clear roadmap for full Owner Mode experience

---

## 📄 New Documentation

### `UX_TRANSFORMATION_SUMMARY.md` (this file)
Change log and implementation notes

---

## 🎨 Visual Changes

### Before → After

**Main Heading:**
- ❌ "Awaiting Your Decision" (orange icon, text-2xl)
- ✅ **"Owner Inbox"** (teal inbox icon, text-3xl)

**Action Cards:**
- ❌ No attribution, "Approve/Deny" buttons
- ✅ **"GM Recommends" badge**, "Accept/Decline" buttons, "Why?" explainer

**Coach Bar:**
- ❌ "3 Actions" button
- ✅ **"3 Decisions"** button with ⌘K hint

**Activity Feed:**
- ❌ Primary focus, text-xl heading
- ✅ Secondary position, text-lg muted heading

---

## 🔧 Backend Data Needs

To fully implement the Owner Mode experience, the backend should provide:

1. **Projected Delta** - `+2.4 pts` improvement per recommendation
2. **Data Freshness** - Timestamp of last projection update
3. **Confidence Score** - 0-100% based on data quality
4. **Win Probability** - Current matchup odds
5. **Lineup Risk** - Injury/bye exposure score
6. **Staleness Indicator** - Flag when projections >4h old
7. **Next Auto-Run** - Timestamp for scheduled scans

**API Endpoint Suggestion:**
```json
GET /api/dashboard/summary
{
  "pending_count": 3,
  "win_probability": 62,
  "lineup_risk": "low",
  "data_freshness": "2024-10-04T10:30:00Z",
  "projections_age_hours": 2,
  "next_auto_run": {
    "type": "lineup_check",
    "scheduled_at": "2024-10-05T09:00:00Z"
  }
}
```

---

## 🚀 Next Steps (Recommended Priority)

### Phase 2: Core Interactions
1. **Command Palette (⌘K)** - Global fuzzy search + preset actions
2. **Keyboard Shortcuts** - A/D for Accept/Decline
3. **Optimistic UI** - Instant feedback with Undo within 5min
4. **Data Freshness Badges** - Show "Projections • 4h old" in amber if stale

### Phase 3: Decision Support
5. **Player Drawer** - Slide-over with full context on click
6. **Projected Delta Badges** - Show +X.X pts prominently on each card
7. **Batch Actions** - "Accept all lineup changes (3)" button
8. **Snooze Management** - Resurface at smart times

### Phase 4: Automation
9. **Auto-Loop Toggles** - Schedule Thu lineup checks, Tue waiver scans
10. **Weekly Cadence Banner** - Visual timeline with auto toggles
11. **Conflict Resolution** - Handle Yahoo state changes gracefully
12. **Post-Week Retros** - Automated Mon evening learnings

---

## 📊 Differentiators vs Yahoo Fantasy

What makes this an **Owner Mode** experience:

| Feature | Yahoo | Owner Mode (This App) |
|---------|-------|----------------------|
| **Mental Model** | Manual manager | AI-assisted owner |
| **Primary View** | Roster grid | Prioritized decision inbox |
| **Actions** | Navigate to make changes | Accept/decline recommendations |
| **Explanations** | None | Every rec has "Why?" with data |
| **Freshness** | Unknown | Staleness badges everywhere |
| **Automation** | None | Auto-scans with toggles |
| **Learning** | None | Weekly retros + process tweaks |
| **Reversibility** | Manual undo | Optimistic UI with 5min undo |

---

## 🎯 Success Metrics

Track these to measure Owner Mode adoption:

1. **Decision latency** - Time from GM recommendation to Owner action
2. **Accept rate** - % of recommendations accepted vs declined
3. **Undo rate** - % of accepted recs that get undone (should be <5%)
4. **Auto-loop adoption** - % of users with ≥1 auto-scan enabled
5. **Command palette usage** - % of actions via ⌘K vs manual buttons
6. **Weekly retro views** - % of users viewing Monday learnings

Target: 80% of actions via Accept/Decline (not manual navigation to Yahoo)

---

## 🔍 Code Changes Summary

### Files Modified
- `app/templates/index.html` - Owner Inbox section, Coach Bar, Activity Feed
- `app/templates/components/action_card.html` - GM attribution, Accept/Decline, Why? button

### Files Created
- `OWNER_PROMPTS.md` - AI prompt library
- `UX_TRANSFORMATION_SUMMARY.md` - This summary

### Lines Changed
- ~150 lines modified
- ~200 lines of documentation added
- 20+ TODO markers for next phase

---

## 🧪 Testing Notes

Before deploying to production:

1. **Visual regression** - Compare Owner Inbox rendering with/without pending recs
2. **Mobile responsiveness** - Test Accept/Decline buttons on small screens
3. **Accessibility** - Verify ARIA labels with screen reader
4. **Toast timing** - Confirm Undo toast appears for 4s
5. **Coach Bar updates** - Verify "3 Decisions" updates after Accept/Decline
6. **Empty states** - Test inbox with 0 pending recommendations

---

## 💡 Design Philosophy

This transformation follows these principles:

1. **Owner, not operator** - You make decisions; AI does research
2. **Transparent AI** - Every recommendation shows its reasoning
3. **Reversible by default** - All actions have undo windows
4. **Fresh data, visible age** - Staleness is never hidden
5. **Automation with oversight** - Auto-scans + owner approval gates
6. **Learning loop** - System improves based on your feedback

---

## 📝 Commit Message

```
Transform UX from GM log to Owner inbox

The previous UI treated users as GMs reviewing activity logs.
This change flips the paradigm: users are Owners making decisions
based on AI GM recommendations.

Key changes:
- "Awaiting Your Decision" → "Owner Inbox" with larger heading
- Action cards now show "GM Recommends" badge
- "Approve/Deny" → "Accept/Decline" for owner-centric language
- Activity Feed demoted to secondary position
- Added ⌘K hint on Coach Bar for future command palette
- Created OWNER_PROMPTS.md with preset AI commands

This establishes the foundation for command palette, auto-loop
scans, and batch actions in future iterations.
```

---

## 🤝 Feedback Loop

To improve Owner Mode, collect:

1. **Accepted recs that underperformed** - Why did the GM get it wrong?
2. **Declined recs that outperformed** - What context did the GM miss?
3. **Snoozed recs that expired** - Should we resurface earlier?
4. **Manual Yahoo changes** - What did users do outside the app?

Feed this back into AI prompt engineering and data prioritization.

