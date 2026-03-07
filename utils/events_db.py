"""
EVENTS DATABASE MANAGER
========================
Manages fintel_events.db — the reference layer for all market events,
regimes, and tech cycles.

Separate from fintel_historical.db by design:
  - Events can be updated, extended, and re-imported without touching IPO data
  - New analytical fields added via event_attributes (key-value) — no schema changes
  - Future agents (signal analyst, backtester) can query events independently

Usage:
    from utils.events_db import init_events_db, get_events_in_window

    init_events_db()   # Call once at startup — idempotent
"""

import os
import sqlite3
from datetime import datetime

ROOT     = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH  = os.path.join(ROOT, "fintel_events.db")


# ── REGIME DEFINITIONS ────────────────────────────────────────────────────────

REGIME_DEFINITIONS = [
    # (regime_id, start_date, end_date, label, description, macro_driver)
    ("early_internet",           "1993-01-01", "1996-12-31",
     "Early Internet Commercialisation",
     "Mosaic browser 1993. Netscape 1994. Amazon/eBay IPOs 1995. First consumer internet wave. Low rates. Retail investing begins.",
     "low_rates_expansion"),

    ("dotcom_euphoria",          "1997-01-01", "2000-03-09",
     "Dot-com Euphoria",
     "P/E ratios abandoned. Eyeballs over revenue. 400+ internet IPOs/year. NASDAQ tripled. Underwriters rubber-stamped anything tech.",
     "irrational_exuberance"),

    ("dotcom_crash",             "2000-03-10", "2002-09-30",
     "Dot-com Crash",
     "NASDAQ -78%. 50%+ of dot-com IPOs delisted by 2004. 9/11 accelerated selloff. Enron/WorldCom fraud shattered trust.",
     "crash_recession"),

    ("sarbanes_oxley_era",       "2002-10-01", "2004-12-31",
     "Sarbanes-Oxley Compliance Era",
     "SOX 2002: massive compliance burden. IPO volume collapsed. Only real-fundamental companies came public. Best quality vintage.",
     "regulatory_tightening"),

    ("credit_boom_recovery",     "2005-01-01", "2007-06-30",
     "Credit Boom Recovery",
     "PE boom. LBO wave. Housing bubble. IPO market reopened. China growth story boosted commodities and EM IPOs.",
     "credit_expansion"),

    ("pre_gfc_peak",             "2007-07-01", "2008-09-14",
     "Pre-GFC Peak and Cracks",
     "Subprime cracks visible. Bear Stearns hedge funds collapsed Jul 2007. IPO window narrowed. Only established names got through.",
     "leverage_peak"),

    ("gfc_acute",                "2008-09-15", "2009-06-30",
     "GFC Acute Phase",
     "Lehman day → near-total IPO shutdown. Zero significant US IPOs Q4 2008. TARP, Fed emergency cuts to 0%.",
     "systemic_crisis"),

    ("gfc_recovery_qe1_qe2",     "2009-07-01", "2012-12-31",
     "GFC Recovery / QE1-QE2",
     "QE1 Nov 2008, QE2 Nov 2010. Risk assets recovered. Tech IPOs resumed cautiously. LinkedIn 2011, Zillow 2011.",
     "qe_stimulus"),

    ("qe3_secular_bull",         "2013-01-01", "2015-07-31",
     "QE3 Secular Bull",
     "QE3 unlimited Sep 2012. Twitter, Facebook second leg. Unicorn era begins. $1B+ private valuations normalised.",
     "qe_expansion"),

    ("china_volatility",         "2015-08-01", "2016-12-31",
     "China Volatility and Trade Fears",
     "China yuan devaluation Aug 2015. S&P correction -12%. IPO market froze. Brexit Jun 2016. Trump win Nov 2016.",
     "geopolitical_uncertainty"),

    ("trump_deregulation_bull",  "2017-01-01", "2018-09-30",
     "Trump Deregulation Bull",
     "Tax cuts Dec 2017. Deregulation. S&P +50% from 2016 lows. Snap 2017, Spotify direct listing 2018.",
     "fiscal_stimulus_deregulation"),

    ("rate_fear_correction",     "2018-10-01", "2019-02-28",
     "Rate Fear Correction",
     "Fed hiking cycle peak. Q4 2018: S&P -20%. IPO window closed. Powell pivoted Feb 2019.",
     "rate_tightening_fear"),

    ("late_cycle_goldilocks",    "2019-03-01", "2020-02-19",
     "Late Cycle Goldilocks",
     "Trade war truce. Rate cuts. Uber, Lyft, Pinterest IPOs (all disappointed). WeWork implosion damaged SPAC credibility.",
     "late_cycle_expansion"),

    ("covid_crash",              "2020-02-20", "2020-04-30",
     "COVID-19 Crash",
     "Fastest -30% in market history. IPO market shut instantly. Fed: unlimited QE within 3 weeks. ZIRP restored.",
     "pandemic_shock"),

    ("covid_zirp_spac_boom",     "2020-05-01", "2021-11-30",
     "COVID ZIRP / SPAC Boom",
     "Greatest IPO+SPAC wave since dot-com. 600+ SPACs in 2021. Retail FOMO via Robinhood. Airbnb, DoorDash, Snowflake record pops.",
     "zirp_liquidity_flood"),

    ("peak_bubble_unwinding",    "2021-12-01", "2022-03-15",
     "Peak Bubble Unwinding",
     "Inflation signals. ARKK -75%. Growth stocks sold off before rate hikes. SPAC bubble deflating. Many 2021 IPOs -60-80%.",
     "inflation_bubble_peak"),

    ("rate_hike_shock",          "2022-03-16", "2023-03-09",
     "Rate Hike Shock",
     "Fed 0% → 4.5% in 12 months. Fastest hiking cycle since 1980. Only 71 US IPOs in 2022 vs 400+ in 2021.",
     "aggressive_tightening"),

    ("svb_stabilisation",        "2023-03-10", "2023-12-31",
     "SVB Crisis and Stabilisation",
     "SVB collapse Mar 2023. Fed paused hikes. ARM, Instacart, Klaviyo: tentative IPO reopening. AI narrative elevated tech.",
     "banking_stress_recovery"),

    ("ai_era_acceleration",      "2024-01-01", "2099-12-31",
     "AI Era Acceleration",
     "Nvidia $3T market cap. AI infrastructure spending cycle confirmed. Rate cuts Sep 2024. Trump 2.0 deregulation. Tariff uncertainty.",
     "ai_infrastructure_cycle"),
]


# ── TECH CYCLE DEFINITIONS ────────────────────────────────────────────────────

TECH_CYCLE_DEFINITIONS = [
    # (cycle_id, start_date, end_date, label, description, dominant_technology)
    ("internet_1_0",           "1993-01-01", "1999-12-31",
     "Internet 1.0",
     "Mosaic to Netscape to Amazon. Desktop software and dial-up internet. CD-ROM distribution. HTML static pages.",
     "browser_internet"),

    ("internet_hangover",      "2000-01-01", "2006-12-31",
     "Internet Hangover and Rebuild",
     "Dot-com survivors rebuilt on real revenue. Google proved search advertising. Open source undermined proprietary software.",
     "search_advertising"),

    ("mobile_revolution",      "2007-01-01", "2012-12-31",
     "Mobile Smartphone Revolution",
     "iPhone Jan 2007. Android Oct 2008. App Store Jul 2008. Every sector had to rebuild for mobile. Location services unlocked.",
     "mobile_apps"),

    ("cloud_saas_platform",    "2010-01-01", "2016-12-31",
     "Cloud / SaaS / Platform Era",
     "AWS dominance. Salesforce proved SaaS. Stripe, Twilio, Shopify built on APIs. Platform businesses showed asset-light model.",
     "cloud_infrastructure"),

    ("data_ml_first_wave",     "2015-01-01", "2020-12-31",
     "Data Science and ML First Wave",
     "Deep learning post-ImageNet 2012 reached commercial impact. TensorFlow 2015, PyTorch 2016. NVIDIA GPU-for-AI pivot begins.",
     "machine_learning"),

    ("ev_clean_tech",          "2019-01-01", "2022-12-31",
     "EV and Clean Tech Boom",
     "Tesla NASDAQ inclusion Dec 2020. EV IPO wave via SPACs (Rivian, Lucid, Arrival). Solar/wind cost curves crossed fossil fuels.",
     "electric_vehicles"),

    ("semiconductor_supercycle","2020-01-01", "2099-12-31",
     "Semiconductor Supercycle",
     "COVID chip shortage revealed strategic dependency. CHIPS Act 2022. TSMC/Intel/Samsung US fabs. AMD overtook Intel in servers.",
     "semiconductors_ai_chips"),

    ("generative_ai",          "2022-11-30", "2099-12-31",
     "Generative AI Era",
     "ChatGPT Nov 2022. GPT-4, Claude, Gemini, Llama. NVIDIA $300B to $3T in 18 months. Every IPO in AI adjacency repriced upward.",
     "large_language_models"),
]


# ── EVENTS ────────────────────────────────────────────────────────────────────

ALL_EVENTS = [
    # (event_id, event_date, category, subcategory, name, description, market_impact, sectors_affected)

    # ── MARKET CRASHES ──────────────────────────────────────────────────────
    ("black_monday_1987",      "1987-10-19", "market_crash",   "equity",
     "Black Monday",
     "DJIA -22.6% in one day — largest single-day crash in history. Program trading and portfolio insurance blamed.",
     "severe_negative", "all"),

    ("dot_com_peak",           "2000-03-10", "market_crash",   "equity",
     "Dot-com Peak",
     "NASDAQ hit 5,048 — all-time high before 78% collapse. Valuations based on eyeballs not revenue finally corrected.",
     "severe_negative", "technology"),

    ("enron_collapse",         "2001-12-02", "market_crash",   "corporate",
     "Enron Collapse",
     "Largest US bankruptcy at time. Mark-to-market accounting fraud. Arthur Andersen collapsed. SOX legislation followed.",
     "moderate_negative", "energy,financials"),

    ("worldcom_fraud",         "2002-07-21", "market_crash",   "corporate",
     "WorldCom Bankruptcy",
     "$11B accounting fraud. Largest US bankruptcy ever at time. Accelerated SOX legislation. Telecom sector devastated.",
     "moderate_negative", "telecom"),

    ("lehman_collapse",        "2008-09-15", "market_crash",   "systemic",
     "Lehman Brothers Collapse",
     "GFC trigger. $600B+ bankruptcy. Credit markets froze globally. Interbank lending stopped. Reserve Primary Fund broke the buck.",
     "severe_negative", "financials,all"),

    ("flash_crash_2010",       "2010-05-06", "market_crash",   "technical",
     "Flash Crash 2010",
     "DJIA -9% in minutes then recovered same day. High-frequency trading and algorithmic cascades blamed. SEC investigated.",
     "mild_negative", "all"),

    ("covid_crash",            "2020-02-20", "market_crash",   "macro",
     "COVID-19 Crash",
     "Fastest -30% decline in S&P history in 23 trading days. IPO market shut instantly. Travel, hospitality, retail devastated.",
     "severe_negative", "all"),

    ("archegos_implosion",     "2021-03-26", "market_crash",   "corporate",
     "Archegos Capital Implosion",
     "$100B+ in forced selling. Credit Suisse lost $5.5B, Nomura $2.9B. Hidden leverage via total return swaps exposed.",
     "moderate_negative", "media,financials"),

    ("svb_collapse",           "2023-03-10", "market_crash",   "banking",
     "Silicon Valley Bank Collapse",
     "Largest US bank failure since 2008. $212B in assets. Held long-duration bonds that lost value as rates rose. Bank run in 48 hours.",
     "moderate_negative", "technology,banking"),

    ("signature_bank",         "2023-03-12", "market_crash",   "banking",
     "Signature Bank Shutdown",
     "Regulators closed crypto-linked bank 2 days after SVB. $110B in assets. Systemic risk fear intensified briefly.",
     "mild_negative", "crypto,banking"),

    # ── FEDERAL RESERVE / MACRO POLICY ──────────────────────────────────────
    ("greenspan_irrational",   "1996-12-05", "macro_policy",   "fed_speech",
     "Greenspan Irrational Exuberance",
     "First public warning of asset bubble. Markets ignored it and rallied 3 more years. Classic central banker dilemma.",
     "mild_negative_ignored", "all"),

    ("fed_y2k_liquidity",      "1999-10-01", "macro_policy",   "liquidity",
     "Fed Y2K Liquidity Injection",
     "Fed flooded system pre-Y2K. Extra liquidity added fuel to dot-com bubble final leg. Withdrew it Jan 2000.",
     "mild_positive", "all"),

    ("fed_emergency_cuts_01",  "2001-01-03", "macro_policy",   "rate_cut",
     "Fed Emergency Inter-Meeting Cut",
     "First inter-meeting cut since 1998. Signal of serious recession concern. Start of 11 consecutive cuts.",
     "moderate_positive", "all"),

    ("qe1_launch",             "2008-11-25", "macro_policy",   "qe",
     "Fed QE1 Launch",
     "$600B mortgage bond purchases. First ever QE in US history. Changed central banking forever. Dollar fell.",
     "strong_positive", "all"),

    ("qe2_launch",             "2010-11-03", "macro_policy",   "qe",
     "Fed QE2 Launch",
     "$600B Treasury purchases. Bernanke defended in Washington Post op-ed. S&P rallied 25% over next 8 months.",
     "strong_positive", "all"),

    ("qe3_launch",             "2012-09-13", "macro_policy",   "qe",
     "Fed QE3 Unlimited",
     "Open-ended $85B/month. 'Whatever it takes' US version. IPO market re-opened fully. Risk assets surged.",
     "strong_positive", "all"),

    ("taper_tantrum",          "2013-05-22", "macro_policy",   "taper",
     "Taper Tantrum",
     "Bernanke hints at QE tapering. 10yr yield +100bps in weeks. EM currencies crashed. Growth stocks sold off briefly.",
     "moderate_negative", "emerging_markets,bonds"),

    ("qe3_end",                "2014-10-29", "macro_policy",   "taper",
     "QE3 Ends",
     "Fed ends bond buying after tapering from $85B to $0 over 10 months. S&P continued higher but at slower pace.",
     "mild_negative", "all"),

    ("first_post_gfc_hike",    "2015-12-16", "macro_policy",   "rate_hike",
     "First Post-GFC Rate Hike",
     "Fed raised rates for first time since 2006. Signalled normalisation. Dollar surged. EM debt stress.",
     "mild_negative", "emerging_markets,real_estate"),

    ("fed_powell_pivot_2019",  "2019-01-04", "macro_policy",   "pivot",
     "Fed Powell Pivot",
     "Powell signals pause in hikes after Q4 2018 crash. Markets reversed all Q4 2018 losses within 3 months.",
     "strong_positive", "all"),

    ("fed_zirp_covid",         "2020-03-15", "macro_policy",   "emergency",
     "Fed Emergency ZIRP + Unlimited QE",
     "Rates to 0%. Unlimited QE announced. Forward guidance locked low. Enabled SPAC/IPO boom. Dollar weakened 10%.",
     "strong_positive", "all"),

    ("fed_inflation_pivot",    "2021-11-22", "macro_policy",   "pivot",
     "Fed Drops Transitory",
     "Powell drops 'transitory' inflation language. Taper acceleration. Growth/speculative stocks began -40-80% declines.",
     "strong_negative", "growth_tech,spacs"),

    ("fed_first_hike_2022",    "2022-03-16", "macro_policy",   "rate_hike",
     "First 2022 Rate Hike",
     "Start of fastest hiking cycle since 1980. 0% → 5.25% in 16 months. Crushed IPO market, growth stocks, crypto.",
     "severe_negative", "growth_tech,real_estate,crypto"),

    ("fed_peak_rates_2023",    "2023-09-20", "macro_policy",   "rate_hold",
     "Fed Reaches Peak Rates",
     "Final hike to 5.25-5.5%. Held for 12 months. IPO market slowly reopened. ARM IPO Sep 2023 tested the waters.",
     "mild_positive", "all"),

    ("fed_first_cut_2024",     "2024-09-18", "macro_policy",   "rate_cut",
     "Fed First Rate Cut 2024",
     "50bps cut. Easing cycle begins. IPO pipeline improved. Risk assets responded positively across the board.",
     "moderate_positive", "all"),

    # ── GEOPOLITICAL ────────────────────────────────────────────────────────
    ("nine_eleven",            "2001-09-11", "geopolitical",   "terrorism",
     "9/11 Attacks",
     "Markets closed 4 days. S&P -11.6% on reopen. Defense/security sector permanently repriced. Aviation devastated.",
     "severe_negative", "defense,aviation,insurance"),

    ("iraq_war",               "2003-03-20", "geopolitical",   "war",
     "Iraq War Invasion",
     "Oil price surge. Initial market uncertainty quickly reversed. Defense stocks surged. Reconstruction contracts.",
     "mixed", "defense,energy"),

    ("hurricane_katrina",      "2005-08-29", "geopolitical",   "natural_disaster",
     "Hurricane Katrina",
     "Energy infrastructure damage in Gulf of Mexico. Oil hit $70/barrel. Insurance sector $80B+ losses.",
     "moderate_negative", "energy,insurance"),

    ("arab_spring",            "2011-01-25", "geopolitical",   "political",
     "Arab Spring Begins",
     "Tunisia → Egypt → Libya → Syria. Oil price spike. MENA political risk repriced. Social media role in protest noted.",
     "moderate_negative", "energy,emerging_markets"),

    ("euro_debt_crisis",       "2010-05-02", "geopolitical",   "sovereign",
     "European Debt Crisis Peak",
     "Greece $110B bailout. EUR collapse fear. ECB Draghi 'whatever it takes' Jul 2012 resolved it. PIIGS sovereign spreads blew out.",
     "moderate_negative", "financials,european_equities"),

    ("russia_crimea",          "2014-02-27", "geopolitical",   "war",
     "Russia Annexes Crimea",
     "First European territorial change since WWII. Energy sanctions. Russian market -30%. European energy risk repriced.",
     "moderate_negative", "energy,european_equities"),

    ("china_circuit_breakers", "2016-01-04", "geopolitical",   "market_structure",
     "China Circuit Breakers Triggered",
     "New circuit breakers triggered twice in one week. Global contagion fear. Policy reversed in days. EM contagion.",
     "moderate_negative", "china,emerging_markets"),

    ("brexit_vote",            "2016-06-23", "geopolitical",   "political",
     "Brexit Referendum",
     "UK votes 52% Leave. GBP -10% overnight. Largest single-day FX move in history. 3-year negotiation uncertainty.",
     "moderate_negative", "uk_equities,eur"),

    ("trump_election_1",       "2016-11-08", "geopolitical",   "political",
     "Trump Election 2016",
     "Unexpected win. S&P initially fell -5% overnight then surged. Infrastructure, defense, banks re-rated upward.",
     "moderate_positive", "defense,financials,infrastructure"),

    ("us_china_trade_war",     "2018-07-06", "geopolitical",   "trade",
     "US-China Trade War Begins",
     "First $34B tariff tranche on Chinese goods. Retaliation followed. Supply chain disruption. Tech semiconductors exposed.",
     "moderate_negative", "technology,semiconductors,industrials"),

    ("us_china_phase1_deal",   "2020-01-15", "geopolitical",   "trade",
     "US-China Phase 1 Trade Deal",
     "Temporary truce. Markets rallied short-term. Structural tech decoupling continued regardless.",
     "mild_positive", "technology,agriculture"),

    ("covid_pandemic_declared","2020-03-11", "geopolitical",   "pandemic",
     "WHO Declares COVID Pandemic",
     "Official pandemic. Lockdowns globally within days. Fastest economic shutdown ever. Remote work became permanent.",
     "severe_negative", "all"),

    ("russia_ukraine_war",     "2022-02-24", "geopolitical",   "war",
     "Russia Invades Ukraine",
     "Largest European war since WWII. European energy crisis. Commodity supercycle. Defense and energy stocks surged.",
     "severe_negative_selective", "defense,energy,agriculture"),

    ("israel_hamas_war",       "2023-10-07", "geopolitical",   "war",
     "Israel-Hamas War Begins",
     "Middle East risk premium repriced. Oil spike. Defense stocks rally. Red Sea shipping disruption +40% shipping rates.",
     "moderate_negative_selective", "defense,energy,shipping"),

    ("trump_election_2",       "2024-11-05", "geopolitical",   "political",
     "Trump Election 2024",
     "Markets surged following day. Deregulation, crypto, defense, tariff themes emerged. Solar/clean energy sold off.",
     "positive_selective", "defense,crypto,financials,energy"),

    ("trump_tariffs_liberation","2025-04-02", "geopolitical",  "trade",
     "Liberation Day Tariffs",
     "Sweeping global tariffs announced. S&P -15% in 3 days. 90-day pause announced. Supply chain restructuring accelerated.",
     "severe_negative", "all"),

    # ── TECHNOLOGY INFLECTION POINTS ─────────────────────────────────────────
    ("netscape_ipo",           "1995-08-09", "tech_event",     "ipo_milestone",
     "Netscape IPO",
     "First major internet IPO. Stock doubled on day 1 from $14 to $28. Opened the dot-com floodgates. Marc Andreessen famous.",
     "strong_positive_tech", "technology"),

    ("google_ipo",             "2004-08-19", "tech_event",     "ipo_milestone",
     "Google IPO",
     "Dutch auction IPO at $85. Proved internet advertising model post dot-com. First profitable internet IPO at scale.",
     "strong_positive_tech", "technology,advertising"),

    ("youtube_acquisition",    "2006-10-09", "tech_event",     "ma_milestone",
     "Google Acquires YouTube",
     "$1.65B cash. First mega web2.0 acquisition. Video internet era confirmed. UGC platform model validated.",
     "moderate_positive_tech", "technology,media"),

    ("iphone_launch",          "2007-01-09", "tech_event",     "product_launch",
     "iPhone Launch",
     "Mobile internet era begins. Entire software industry rebuilt for touchscreen. Nokia, BlackBerry, Motorola disrupted.",
     "transformative", "technology,telecom,mobile"),

    ("app_store_launch",       "2008-07-10", "tech_event",     "platform_launch",
     "Apple App Store Opens",
     "3rd party app ecosystem. New IPO vertical: mobile-first apps. 10M downloads in 3 days. Developer economy born.",
     "transformative", "technology,mobile"),

    ("aws_ec2_ga",             "2008-10-23", "tech_event",     "platform_launch",
     "AWS EC2 Generally Available",
     "Cloud computing became real infrastructure. Killed 'we need our own servers' argument. IaaS market created.",
     "transformative", "technology,cloud"),

    ("bitcoin_genesis",        "2009-01-03", "tech_event",     "crypto",
     "Bitcoin Genesis Block",
     "Crypto era begins. Satoshi Nakamoto mines first block. Low IPO relevance until 2020 crypto company wave.",
     "low_initial", "crypto"),

    ("facebook_ipo",           "2012-05-18", "tech_event",     "ipo_milestone",
     "Facebook IPO",
     "Largest tech IPO at time. Initially disappointing (NASDAQ glitch). Social media advertising model proven at scale.",
     "moderate_positive_tech", "technology,advertising,social"),

    ("imagenet_deep_learning", "2012-10-01", "tech_event",     "ai_milestone",
     "AlexNet Wins ImageNet 2012",
     "Deep learning error rate: 15.3% vs 26% prior year. Hinton, Krizhevsky, Sutskever. AI research explosion began.",
     "delayed_transformative", "technology,ai"),

    ("alibaba_ipo",            "2014-09-19", "tech_event",     "ipo_milestone",
     "Alibaba IPO",
     "Largest IPO in history at time — $25B raised. China tech credibility peak. EM tech IPO wave followed.",
     "strong_positive", "technology,ecommerce,china"),

    ("alphago_world_1",        "2016-03-15", "tech_event",     "ai_milestone",
     "AlphaGo Beats Lee Sedol",
     "AI beats world Go champion 4-1. Go was considered too complex for AI. Enterprise AI investment began accelerating.",
     "moderate_positive_ai", "technology,ai"),

    ("nvidia_datacenter_pivot","2018-05-10", "tech_event",     "sector_pivot",
     "Nvidia Datacenter Exceeds Gaming Revenue",
     "GPU-for-AI became larger than gaming. Semiconductor sector re-rated. Nvidia's 10-year dominance began here.",
     "strong_positive", "semiconductors,ai"),

    ("wework_ipo_collapse",    "2019-09-30", "tech_event",     "ipo_failure",
     "WeWork IPO Withdrawal",
     "$47B private valuation → $10B real valuation. Neumann ousted. Inflated unicorn valuations broadly questioned.",
     "negative_for_overvalued", "real_estate_tech,spacs"),

    ("snowflake_ipo",          "2020-09-16", "tech_event",     "ipo_milestone",
     "Snowflake IPO — Record Pop",
     "Largest software IPO ever at time. 111% first day gain. Data cloud thesis confirmed. Warren Buffett invested pre-IPO.",
     "strong_positive_tech", "technology,data,cloud"),

    ("airbnb_doordash_ipo",    "2020-12-10", "tech_event",     "ipo_milestone",
     "Airbnb + DoorDash IPOs",
     "Both doubled on day 1 in Dec 2020 ZIRP peak. Retail FOMO at maximum. Gig economy and platform models confirmed.",
     "strong_positive", "technology,marketplace"),

    ("coinbase_direct_listing","2021-04-14", "tech_event",     "ipo_milestone",
     "Coinbase Direct Listing",
     "First major crypto exchange public. $85B peak valuation day 1. Crypto sector IPO barometer. Later fell -90%.",
     "positive_short_negative_long", "crypto,financials"),

    ("rivian_ipo",             "2021-11-10", "tech_event",     "ipo_milestone",
     "Rivian IPO — EV Bubble Peak",
     "$12B raise. Briefly larger market cap than Ford+GM combined. Marked EV SPAC/IPO bubble absolute peak.",
     "negative_signal_for_ev", "ev,automotive"),

    ("chips_act_signed",       "2022-08-09", "tech_event",     "regulatory",
     "US CHIPS Act Signed",
     "$52B US semiconductor manufacturing subsidies. Intel, TSMC, Samsung announced US fabs. Strategic decoupling accelerated.",
     "strong_positive", "semiconductors,manufacturing"),

    ("chatgpt_launch",         "2022-11-30", "tech_event",     "ai_milestone",
     "ChatGPT Public Launch",
     "100M users in 60 days — fastest growing consumer app ever. OpenAI's $29B valuation. AI investment theme ignited globally.",
     "transformative", "technology,ai,all"),

    ("nvidia_q1_2023_earnings","2023-05-24", "tech_event",     "earnings_shock",
     "Nvidia Q1 2023 Earnings Shock",
     "Revenue guidance doubled vs expectations. GPU demand for AI confirmed at enterprise scale. NVDA +25% overnight.",
     "strong_positive", "semiconductors,ai,data_centers"),

    ("arm_ipo_2023",           "2023-09-14", "tech_event",     "ipo_milestone",
     "ARM Holdings IPO",
     "First major tech IPO in 18 months. $54B valuation. Reopened the IPO market. Semiconductor IP model revalued.",
     "moderate_positive", "semiconductors,technology"),

    ("openai_gpt4_launch",     "2023-03-14", "tech_event",     "ai_milestone",
     "GPT-4 Launch",
     "Multimodal LLM. Bar exam top 10%. Massive enterprise adoption wave. Microsoft Copilot integration began.",
     "strong_positive_ai", "technology,ai,enterprise_software"),

    ("deepseek_shock",         "2025-01-27", "tech_event",     "ai_milestone",
     "DeepSeek R1 Release",
     "Chinese open-source AI matched GPT-4 at fraction of compute cost. Nvidia -17% in one day. AI efficiency paradigm shift.",
     "negative_for_infrastructure", "semiconductors,ai,data_centers"),

    ("meta_llama_open_source", "2023-07-18", "tech_event",     "ai_milestone",
     "Meta Releases Llama Open Source",
     "First capable open-source LLM. Democratised AI development. Undermined closed-model moats. Enterprise AI adoption accelerated.",
     "mixed", "technology,ai"),
]


# ── EVENT ATTRIBUTE TEMPLATES ─────────────────────────────────────────────────
# Pre-populate known analytical dimensions — more can be added any time
# without schema changes

DEFAULT_EVENT_ATTRIBUTES = [
    # Severity for quantitative use in model features
    # (event_id, attribute_key, attribute_value, data_type, source)
    # We auto-generate these from market_impact in ALL_EVENTS
]


# ── DB FUNCTIONS ──────────────────────────────────────────────────────────────

def get_connection():
    return sqlite3.connect(DB_PATH)


def init_events_db():
    """
    Create and seed fintel_events.db.
    Idempotent — safe to call multiple times.
    New events/regimes are added; existing ones are ignored (INSERT OR IGNORE).
    """
    conn = get_connection()
    c    = conn.cursor()

    # Regimes table
    c.execute("""
        CREATE TABLE IF NOT EXISTS regime_definitions (
            regime_id       TEXT PRIMARY KEY,
            start_date      TEXT,
            end_date        TEXT,
            label           TEXT,
            description     TEXT,
            macro_driver    TEXT,
            created_at      TEXT DEFAULT (datetime('now'))
        )
    """)

    # Tech cycles table
    c.execute("""
        CREATE TABLE IF NOT EXISTS tech_cycle_definitions (
            cycle_id          TEXT PRIMARY KEY,
            start_date        TEXT,
            end_date          TEXT,
            label             TEXT,
            description       TEXT,
            dominant_tech     TEXT,
            created_at        TEXT DEFAULT (datetime('now'))
        )
    """)

    # Events table — richer schema than v1
    c.execute("""
        CREATE TABLE IF NOT EXISTS events (
            event_id          TEXT PRIMARY KEY,
            event_date        TEXT,
            category          TEXT,
            subcategory       TEXT,
            name              TEXT,
            description       TEXT,
            market_impact     TEXT,
            sectors_affected  TEXT,
            created_at        TEXT DEFAULT (datetime('now'))
        )
    """)

    # Flexible key-value attributes — add ANY new analytical dimension
    # without ever altering the events table schema
    c.execute("""
        CREATE TABLE IF NOT EXISTS event_attributes (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id        TEXT NOT NULL,
            attribute_key   TEXT NOT NULL,
            attribute_value TEXT,
            data_type       TEXT,   -- 'float', 'int', 'text', 'bool'
            source          TEXT,   -- where this value came from
            created_at      TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (event_id) REFERENCES events(event_id),
            UNIQUE(event_id, attribute_key)
        )
    """)

    # Audit log — every time events DB is updated, log it
    c.execute("""
        CREATE TABLE IF NOT EXISTS events_update_log (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            updated_at      TEXT DEFAULT (datetime('now')),
            events_added    INTEGER,
            regimes_added   INTEGER,
            tech_cycles_added INTEGER,
            notes           TEXT
        )
    """)

    conn.commit()

    # ── Seed data ──────────────────────────────────────────────────────────
    before_events  = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    before_regimes = conn.execute("SELECT COUNT(*) FROM regime_definitions").fetchone()[0]
    before_cycles  = conn.execute("SELECT COUNT(*) FROM tech_cycle_definitions").fetchone()[0]

    conn.executemany("""
        INSERT OR IGNORE INTO regime_definitions
            (regime_id, start_date, end_date, label, description, macro_driver)
        VALUES (?,?,?,?,?,?)
    """, REGIME_DEFINITIONS)

    conn.executemany("""
        INSERT OR IGNORE INTO tech_cycle_definitions
            (cycle_id, start_date, end_date, label, description, dominant_tech)
        VALUES (?,?,?,?,?,?)
    """, TECH_CYCLE_DEFINITIONS)

    conn.executemany("""
        INSERT OR IGNORE INTO events
            (event_id, event_date, category, subcategory,
             name, description, market_impact, sectors_affected)
        VALUES (?,?,?,?,?,?,?,?)
    """, ALL_EVENTS)

    conn.commit()

    after_events  = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    after_regimes = conn.execute("SELECT COUNT(*) FROM regime_definitions").fetchone()[0]
    after_cycles  = conn.execute("SELECT COUNT(*) FROM tech_cycle_definitions").fetchone()[0]

    added_e = after_events  - before_events
    added_r = after_regimes - before_regimes
    added_c = after_cycles  - before_cycles

    if added_e + added_r + added_c > 0:
        conn.execute("""
            INSERT INTO events_update_log
                (events_added, regimes_added, tech_cycles_added, notes)
            VALUES (?, ?, ?, ?)
        """, (added_e, added_r, added_c, "seeded from constants"))
        conn.commit()

    conn.close()
    return {"events": after_events, "regimes": after_regimes, "tech_cycles": after_cycles}


def get_regime(date_str: str) -> str:
    """Return macro regime_id for a given date."""
    if not date_str:
        return "unknown"
    d = date_str[:10]
    conn = get_connection()
    row = conn.execute("""
        SELECT regime_id FROM regime_definitions
        WHERE start_date <= ? AND end_date >= ?
        ORDER BY start_date DESC LIMIT 1
    """, (d, d)).fetchone()
    conn.close()
    return row[0] if row else "unknown"


def get_tech_cycle(date_str: str) -> str:
    """Return tech cycle_id for a given date."""
    if not date_str:
        return "unknown"
    d = date_str[:10]
    conn = get_connection()
    row = conn.execute("""
        SELECT cycle_id FROM tech_cycle_definitions
        WHERE start_date <= ? AND end_date >= ?
        ORDER BY start_date DESC LIMIT 1
    """, (d, d)).fetchone()
    conn.close()
    return row[0] if row else "unknown"


def get_events_in_window(start_date: str, end_date: str,
                         categories: list = None) -> list[dict]:
    """
    Returns all events between start_date and end_date.
    Optionally filter by category list.
    Used by collect_historical_ipos.py to flag companies.
    """
    conn  = get_connection()
    query = "SELECT * FROM events WHERE event_date BETWEEN ? AND ?"
    params = [start_date, end_date]

    if categories:
        placeholders = ",".join("?" * len(categories))
        query  += f" AND category IN ({placeholders})"
        params += categories

    rows = conn.execute(query, params).fetchall()
    cols = [d[0] for d in conn.execute("SELECT * FROM events LIMIT 0").description]
    conn.close()
    return [dict(zip(cols, row)) for row in rows]


def add_event_attribute(event_id: str, key: str, value, data_type: str = "text", source: str = "manual"):
    """
    Add a new analytical attribute to any event.
    This is the extension point — call this any time you want to add
    a new dimension (e.g. VIX level on event date, S&P return 30d after, etc.)

    Example:
        add_event_attribute("covid_crash", "sp500_return_30d", "-0.34", "float", "yfinance")
        add_event_attribute("chatgpt_launch", "ai_hype_score", "95", "int", "manual")
    """
    conn = get_connection()
    conn.execute("""
        INSERT OR REPLACE INTO event_attributes
            (event_id, attribute_key, attribute_value, data_type, source)
        VALUES (?, ?, ?, ?, ?)
    """, (event_id, key, str(value), data_type, source))
    conn.commit()
    conn.close()


def add_event(event_id: str, event_date: str, category: str, subcategory: str,
              name: str, description: str, market_impact: str = "", sectors_affected: str = ""):
    """
    Add a new event to the events DB at any time.
    Safe to call repeatedly — uses INSERT OR IGNORE.

    Example (add in future when needed):
        add_event("anthropic_claude3", "2024-03-04", "tech_event", "ai_milestone",
                  "Claude 3 Opus Launch", "Matched/exceeded GPT-4 on benchmarks...", ...)
    """
    conn = get_connection()
    conn.execute("""
        INSERT OR IGNORE INTO events
            (event_id, event_date, category, subcategory,
             name, description, market_impact, sectors_affected)
        VALUES (?,?,?,?,?,?,?,?)
    """, (event_id, event_date, category, subcategory,
          name, description, market_impact, sectors_affected))
    conn.execute("""
        INSERT INTO events_update_log (events_added, notes)
        VALUES (1, ?)
    """, (f"manually added: {event_id}",))
    conn.commit()
    conn.close()


if __name__ == "__main__":
    from rich.console import Console
    from rich.table import Table

    console = Console()
    stats   = init_events_db()

    t = Table(title="📚 fintel_events.db — Seeded", header_style="bold cyan")
    t.add_column("Table",  style="dim")
    t.add_column("Count",  justify="right", style="bold green")
    t.add_row("Events",     str(stats["events"]))
    t.add_row("Regimes",    str(stats["regimes"]))
    t.add_row("Tech Cycles",str(stats["tech_cycles"]))
    console.print(t)
    console.print(f"\n[dim]DB: {DB_PATH}[/dim]")
