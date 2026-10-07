# Live schedule integration

The upcoming card can use the [SportsDataIO MMA Schedule and Event feeds](https://sportsdata.io/developers/api-documentation/mma). Set `SPORTSDATAIO_MMA_API_KEY` in the API server environment and restart it. The key stays on the server and must have UFC MMA coverage.

The API fetches the current and next UFC season schedules, then returns the next five announced event cards. Provider fighter names are matched against the accepted canonical roster by exact normalized name. A bout with an unmatched fighter remains visible but its Predict action is disabled; provider IDs are never passed to the prediction model as canonical IDs. Matched bouts open the comparison page with the scheduled date as the feature cutoff.

The provider's published cadence is one hour for schedules and one minute for event detail. The adapter caches fetched cards in process for one hour. Without a key or an available future card, the UI reports schedule unavailability and retains manual fighter selection. The local `data/upcoming.csv` fallback remains unverified and is labeled as such in the UI.

The unavailable state links to UFC's public calendar for human viewing. The app does not scrape that site; [UFC's terms](https://www.ufc.com/terms) prohibit automated page scraping.

The decision chart allocates XGBoost tree-margin contributions to percentage-point changes in the symmetric winner estimate. It groups the accepted 167 features into strength, recent form, career record, striking, grappling, missing history, and other context. The allocation reconciles to the final probability, but correlated features and interactions mean the bars are associations, not causes. The expanded snapshot comparison separately shows raw differences in accepted M4 feature columns.

The fighter carousel uses accepted M3 bouts and reviewed division provenance. It ranks fighters by a Wilson lower-bound win rate over the three years ending on the latest accepted bout date, requiring at least three decisive bouts in that division. It is historical form, not an official or current UFC ranking. No licensed fighter image feed is configured, so the cards use graphic initials.
