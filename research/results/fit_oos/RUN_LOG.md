# RUN_LOG: walk-forward OOS test of the AI fit

* method: research/fit_oos/METHOD.md, commit `e2f1600df1cd`
* command: `cd backend && uv run --group engine --env-file ../.env python scripts/walk_forward_fits.py --method-commit e2f1600df1cd --cache /private/tmp/claude-501/-Users-theomachado-gatorquant/260705e1-1fb4-48f1-9140-9fde9a4d2369/scratchpad/wf_cache --note 'Re-executed from the first execution'"'"'s cached histories (no refetch) only to change chart scaling (symlog), RUN_LOG quoting and add descriptive lines to SUMMARY.md; per_market.csv is byte-identical to the first execution (16:36:36-16:37:13 UTC), so every number is the first run'"'"'s.'`
* started 2026-10-03T16:39:02+00:00, finished 2026-10-03T16:39:03+00:00
* engine: hedgecore (library source `engine`, can_score True), provider rules
* split: train 60% of ticks, purge max(2, ceil(5% n)), test the rest; min 10 ticks per slice; shares 1000
* universe: 122 markets scored in backend/app/data/fits.json
* tick sources: {'live_history': 122}; fetch timeouts: 0
* tested 122, excluded 0
* primary: n = 122, mean -0.4706, median -0.0040; sign 19 > 0 / 72 < 0 (31 = 0), p = 1.000; t = -3.17, p = 0.999; Wilcoxon p = 1.000
* verdict: FAIL
* note: Re-executed from the first execution's cached histories (no refetch) only to change chart scaling (symlog), RUN_LOG quoting and add descriptive lines to SUMMARY.md; per_market.csv is byte-identical to the first execution (16:36:36-16:37:13 UTC), so every number is the first run's.

## Per market

```
      polymarket:5126779 VRT    tested   n=96 train=57 purge=5 test=34 tech_reg_hedge#72 train=0.0313873 test=-0.439606 default=-0.185545 src=live_history (0.0s)
      polymarket:4662693 AMZN   tested   n=379 train=227 purge=19 test=133 tech_reg_hedge#0 train=-9.69273e-05 test=-0.000410546 default=-0.000903831 src=live_history (0.0s)
       polymarket:562831 ICLN   tested   n=721 train=432 purge=37 test=252 equity_delta_bridge#87 train=0.0132321 test=0.00333036 default=0.00164368 src=live_history (0.0s)
      polymarket:2589813 SPY    tested   n=721 train=432 purge=37 test=252 equity_delta_bridge#15 train=-0.00153967 test=0.000432254 default=-0.0125901 src=live_history (0.0s)
       polymarket:562828 ICLN   tested   n=720 train=432 purge=36 test=252 election_hedge#56 train=0.0577937 test=0.000913779 default=0 src=live_history (0.0s)
       polymarket:665374 XLE    tested   n=721 train=432 purge=37 test=252 stress_lead_hedge#29 train=0.0087051 test=-0.244998 default=-0.439623 src=live_history (0.0s)
       polymarket:562802 ICLN   tested   n=721 train=432 purge=37 test=252 equity_delta_bridge#82 train=0.00525959 test=0.0028658 default=0.00137833 src=live_history (0.0s)
      polymarket:5179198 VRT    tested   n=49 train=29 purge=3 test=17 tech_reg_hedge#69 train=0.0576769 test=0 default=0 src=live_history (0.0s) [never hedged on test (0 by construction)]
      polymarket:5170735 IBIT   tested   n=59 train=35 purge=3 test=21 equity_delta_bridge#87 train=0.0883071 test=0 default=0 src=live_history (0.0s) [never hedged on test (0 by construction)]
      polymarket:1365861 EWZ    tested   n=721 train=432 purge=37 test=252 equity_delta_bridge#18 train=0.00841855 test=-0.00645679 default=-0.00582379 src=live_history (0.0s)
      polymarket:4037599 EWZ    tested   n=717 train=430 purge=36 test=251 equity_delta_bridge#105 train=0.122482 test=-0.453665 default=-0.0704735 src=live_history (0.0s)
       polymarket:562803 XLE    tested   n=717 train=430 purge=36 test=251 election_hedge#77 train=0.00758865 test=-1.45205 default=-0.0626084 src=live_history (0.0s)
      polymarket:4985048 IBIT   tested   n=167 train=100 purge=9 test=58 equity_delta_bridge#81 train=0.00520591 test=0 default=0 src=live_history (0.0s) [never hedged on test (0 by construction)]
      polymarket:4985052 IBIT   tested   n=169 train=101 purge=9 test=59 equity_delta_bridge#90 train=0.00976807 test=0 default=0 src=live_history (0.0s) [never hedged on test (0 by construction)]
      polymarket:2589810 IWM    tested   n=719 train=431 purge=36 test=252 stress_lead_hedge#29 train=0.00534667 test=-0.690316 default=-0.61585 src=live_history (0.0s)
      polymarket:5126782 VRT    tested   n=97 train=58 purge=5 test=34 tech_reg_hedge#72 train=0.045529 test=-0.418026 default=-0.162466 src=live_history (0.0s)
      polymarket:4037600 EWZ    tested   n=721 train=432 purge=37 test=252 election_hedge#68 train=0.130784 test=-0.478802 default=-0.0523632 src=live_history (0.0s)
      polymarket:5062249 IBIT   tested   n=132 train=79 purge=7 test=46 equity_delta_bridge#6 train=-0.0758522 test=0 default=-0.7151 src=live_history (0.0s) [never hedged on test (0 by construction)]
      polymarket:2589814 SPY    tested   n=718 train=430 purge=36 test=252 fig_stress#6 train=0.0153538 test=-0.00399806 default=0 src=live_history (0.0s)
      polymarket:5123857 VRT    tested   n=97 train=58 purge=5 test=34 tech_reg_hedge#0 train=-0.0201289 test=-0.0917467 default=-0.164406 src=live_history (0.0s)
      polymarket:2176270 XLE    tested   n=720 train=432 purge=36 test=252 equity_delta_bridge#98 train=0.0146288 test=-0.0481888 default=-0.019135 src=live_history (0.0s)
      polymarket:5164765 XLE    tested   n=67 train=40 purge=4 test=23 equity_delta_bridge#38 train=0.0764972 test=0 default=0 src=live_history (0.0s) [never hedged on test (0 by construction)]
      polymarket:2589811 SPY    tested   n=721 train=432 purge=37 test=252 fig_stress#75 train=0.175438 test=-13.7219 default=-0.15664 src=live_history (0.0s)
      polymarket:4985072 IBIT   tested   n=169 train=101 purge=9 test=59 equity_delta_bridge#81 train=0.216706 test=-0.20962 default=-0.0341479 src=live_history (0.0s)
      polymarket:5062265 IBIT   tested   n=133 train=79 purge=7 test=47 crypto_reg_hedge#2 train=-0.0206319 test=-0.0808361 default=-0.111667 src=live_history (0.0s)
      polymarket:5126781 VRT    tested   n=96 train=57 purge=5 test=34 tech_reg_hedge#63 train=0.0155657 test=-0.238269 default=-0.105502 src=live_history (0.0s)
      polymarket:5062275 COIN   tested   n=132 train=79 purge=7 test=46 crypto_reg_hedge#20 train=0.00750781 test=-0.0557935 default=-0.080436 src=live_history (0.0s)
      polymarket:5179177 VRT    tested   n=49 train=29 purge=3 test=17 tech_reg_hedge#69 train=0.0576769 test=0 default=0 src=live_history (0.0s) [never hedged on test (0 by construction)]
      polymarket:5180113 IBIT   tested   n=48 train=28 purge=3 test=17 crypto_reg_hedge#15 train=0.00079839 test=0 default=0 src=live_history (0.0s) [never hedged on test (0 by construction)]
      polymarket:5126778 VRT    tested   n=95 train=57 purge=5 test=33 tech_reg_hedge#63 train=0.0282763 test=-0.218663 default=-0.0977256 src=live_history (0.0s)
      polymarket:3215007 IWM    tested   n=721 train=432 purge=37 test=252 macro_fed_hedge#55 train=0.161448 test=0.0514989 default=0.0300473 src=live_history (0.0s)
      polymarket:5062278 COIN   tested   n=132 train=79 purge=7 test=46 crypto_reg_hedge#11 train=0.00485584 test=0 default=-0.0298888 src=live_history (0.0s) [never hedged on test (0 by construction)]
      polymarket:4662694 AMZN   tested   n=379 train=227 purge=19 test=133 tech_reg_hedge#0 train=-0.000222438 test=-0.00109291 default=-0.00253334 src=live_history (0.0s)
      polymarket:4662696 SMR    tested   n=377 train=226 purge=19 test=132 equity_delta_bridge#0 train=-0.00631756 test=-0.0026052 default=-0.00558229 src=live_history (0.0s)
      polymarket:4906127 XLE    tested   n=220 train=132 purge=11 test=77 tech_reg_hedge#71 train=0.00763411 test=0.0100471 default=0.00459686 src=live_history (0.0s)
       polymarket:567621 TSM    tested   n=721 train=432 purge=37 test=252 equity_delta_bridge#6 train=0.0024219 test=-0.00309771 default=0.000487171 src=live_history (0.0s)
      polymarket:4641065 XLE    tested   n=384 train=230 purge=20 test=134 equity_delta_bridge#101 train=0.112474 test=-0.933233 default=-0.214255 src=live_history (0.0s)
      polymarket:1107582 XLE    tested   n=720 train=432 purge=36 test=252 stress_lead_hedge#1 train=0.00165054 test=-0.0626269 default=-0.419453 src=live_history (0.0s)
      polymarket:4985083 COIN   tested   n=168 train=100 purge=9 test=59 crypto_reg_hedge#47 train=0.251975 test=0.0180853 default=-0.304079 src=live_history (0.0s)
       polymarket:666861 SPY    tested   n=721 train=432 purge=37 test=252 equity_delta_bridge#90 train=0.000210392 test=0.000556188 default=0.000704264 src=live_history (0.0s)
      polymarket:4985077 COIN   tested   n=168 train=100 purge=9 test=59 crypto_reg_hedge#47 train=0.25119 test=-0.110873 default=-0.0518331 src=live_history (0.0s)
      polymarket:4985067 COIN   tested   n=169 train=101 purge=9 test=59 equity_delta_bridge#81 train=0.131104 test=-0.000323421 default=0 src=live_history (0.0s)
      polymarket:5062327 COIN   tested   n=132 train=79 purge=7 test=46 crypto_reg_hedge#11 train=-0.00380413 test=-0.0597248 default=-0.0636975 src=live_history (0.0s)
      polymarket:3554657 GOOGL  tested   n=721 train=432 purge=37 test=252 equity_delta_bridge#105 train=0.0516787 test=-6.07402 default=-0.233406 src=live_history (0.0s)
      polymarket:5170731 COIN   tested   n=59 train=35 purge=3 test=21 equity_delta_bridge#93 train=0.247305 test=0 default=0 src=live_history (0.0s) [never hedged on test (0 by construction)]
      polymarket:4662584 MSFT   tested   n=378 train=226 purge=19 test=133 tech_reg_hedge#54 train=0.00574434 test=0.00352387 default=-0.000233939 src=live_history (0.0s)
      polymarket:1535973 XLE    tested   n=717 train=430 purge=36 test=251 equity_delta_bridge#84 train=0.00193049 test=0.00963778 default=0.0042179 src=live_history (0.0s)
      polymarket:5179176 EQIX   tested   n=49 train=29 purge=3 test=17 tech_reg_hedge#0 train=-0.0254054 test=0 default=0 src=live_history (0.0s) [never hedged on test (0 by construction)]
      polymarket:2126461 XLE    tested   n=720 train=432 purge=36 test=252 equity_delta_bridge#68 train=0.0161343 test=-0.268559 default=-0.065159 src=live_history (0.0s)
      polymarket:3399459 XLE    tested   n=717 train=430 purge=36 test=251 stress_lead_hedge#35 train=0.0312181 test=-0.231578 default=-0.380874 src=live_history (0.0s)
      polymarket:5170746 COIN   tested   n=59 train=35 purge=3 test=21 equity_delta_bridge#93 train=0.00760503 test=0 default=0 src=live_history (0.0s) [never hedged on test (0 by construction)]
      polymarket:3128888 XLE    tested   n=720 train=432 purge=36 test=252 tech_reg_hedge#68 train=0.0138903 test=-0.0457502 default=-0.0111325 src=live_history (0.0s)
      polymarket:4824013 VLO    tested   n=283 train=169 purge=15 test=99 equity_delta_bridge#90 train=0.0692443 test=0.0322296 default=0.00978334 src=live_history (0.0s)
       polymarket:560317 SPY    tested   n=721 train=432 purge=37 test=252 election_hedge#78 train=0.00643356 test=-1.6026 default=-0.0299466 src=live_history (0.0s)
      polymarket:3491459 XLE    tested   n=721 train=432 purge=37 test=252 equity_delta_bridge#66 train=0.00616873 test=-0.00406461 default=-0.00149768 src=live_history (0.0s)
      polymarket:4620900 TLT    tested   n=406 train=243 purge=21 test=142 equity_delta_bridge#60 train=0.272307 test=-0.244923 default=-1.49769e-05 src=live_history (0.0s)
      polymarket:3215008 TLT    tested   n=720 train=432 purge=36 test=252 macro_fed_hedge#0 train=-0.00563648 test=-0.00607899 default=-0.0257538 src=live_history (0.0s)
      polymarket:3554659 GOOGL  tested   n=721 train=432 purge=37 test=252 tech_reg_hedge#27 train=0.0169875 test=-0.153745 default=-0.176474 src=live_history (0.0s)
       polymarket:562829 SPY    tested   n=721 train=432 purge=37 test=252 equity_delta_bridge#54 train=0.00352009 test=-0.000146736 default=0 src=live_history (0.0s)
      polymarket:5130978 XLE    tested   n=96 train=57 purge=5 test=34 stress_lead_hedge#30 train=0.0733639 test=-2.53021 default=-2.53021 src=live_history (0.0s)
      polymarket:5062258 COIN   tested   n=133 train=79 purge=7 test=47 crypto_reg_hedge#2 train=-0.0400425 test=-0.0180471 default=-0.226873 src=live_history (0.0s)
      polymarket:5170771 COIN   tested   n=59 train=35 purge=3 test=21 equity_delta_bridge#102 train=0.219819 test=0 default=0 src=live_history (0.0s) [never hedged on test (0 by construction)]
      polymarket:4985100 COIN   tested   n=169 train=101 purge=9 test=59 crypto_reg_hedge#73 train=0.242329 test=-2.56697 default=-0.657981 src=live_history (0.0s)
       polymarket:701494 COIN   tested   n=720 train=432 purge=36 test=252 equity_delta_bridge#83 train=0.196476 test=-3.84759 default=-0.0495075 src=live_history (0.0s)
      polymarket:5130977 XLE    tested   n=96 train=57 purge=5 test=34 stress_lead_hedge#27 train=0.0685396 test=-3.06985 default=-2.86759 src=live_history (0.0s)
      polymarket:5123850 AEP    tested   n=99 train=59 purge=5 test=35 tech_reg_hedge#6 train=-0.0111159 test=-0.0301217 default=-0.102626 src=live_history (0.0s)
      polymarket:5170773 ETHA   tested   n=60 train=36 purge=3 test=21 equity_delta_bridge#93 train=0.0762247 test=0 default=0 src=live_history (0.0s) [never hedged on test (0 by construction)]
      polymarket:4985089 IBIT   tested   n=168 train=100 purge=9 test=59 crypto_reg_hedge#47 train=0.291465 test=0.157397 default=-1.18636 src=live_history (0.0s)
      polymarket:5062280 IBIT   tested   n=132 train=79 purge=7 test=46 equity_delta_bridge#102 train=0.0113241 test=0 default=0 src=live_history (0.0s) [never hedged on test (0 by construction)]
      polymarket:5062325 ETHA   tested   n=132 train=79 purge=7 test=46 crypto_reg_hedge#1 train=-0.0191158 test=-0.0754818 default=-0.110598 src=live_history (0.0s)
      polymarket:5170730 IBIT   tested   n=60 train=36 purge=3 test=21 equity_delta_bridge#72 train=0.347589 test=0 default=0 src=live_history (0.0s) [never hedged on test (0 by construction)]
       polymarket:701502 IBIT   tested   n=717 train=430 purge=36 test=251 equity_delta_bridge#93 train=0.000545938 test=-0.00571879 default=-0.00275831 src=live_history (0.0s)
       polymarket:701496 IBIT   tested   n=720 train=432 purge=36 test=252 crypto_reg_hedge#65 train=0.0948316 test=-0.00499027 default=-0.0835526 src=live_history (0.0s)
      polymarket:5126792 AEE    tested   n=97 train=58 purge=5 test=34 tech_reg_hedge#57 train=0.0717307 test=-0.247525 default=-0.0926592 src=live_history (0.0s)
      polymarket:5126795 ETR    tested   n=96 train=57 purge=5 test=34 tech_reg_hedge#60 train=0.0266074 test=-0.126369 default=-0.0899266 src=live_history (0.0s)
      polymarket:5170728 IBIT   tested   n=59 train=35 purge=3 test=21 crypto_reg_hedge#50 train=0.44471 test=0 default=0 src=live_history (0.0s) [never hedged on test (0 by construction)]
      polymarket:4984993 ETHA   tested   n=168 train=100 purge=9 test=59 crypto_reg_hedge#21 train=0.15959 test=0.0851923 default=0.0764793 src=live_history (0.0s)
      polymarket:5170740 IBIT   tested   n=59 train=35 purge=3 test=21 equity_delta_bridge#102 train=0.144263 test=0 default=0 src=live_history (0.0s) [never hedged on test (0 by construction)]
      polymarket:4936105 XLE    tested   n=205 train=123 purge=11 test=71 equity_delta_bridge#25 train=-0.0135558 test=-0.0137184 default=-0.0469102 src=live_history (0.0s)
      polymarket:3501950 XLE    tested   n=717 train=430 purge=36 test=251 equity_delta_bridge#33 train=0.000287089 test=-0.016626 default=-0.0155609 src=live_history (0.0s)
      polymarket:5180122 ETHA   tested   n=49 train=29 purge=3 test=17 crypto_reg_hedge#1 train=-0.0233379 test=0 default=0 src=live_history (0.0s) [never hedged on test (0 by construction)]
       polymarket:701548 ETHA   tested   n=717 train=430 purge=36 test=251 equity_delta_bridge#81 train=0.0181737 test=-0.233321 default=0.0109067 src=live_history (0.0s)
      polymarket:5170744 IBIT   tested   n=59 train=35 purge=3 test=21 equity_delta_bridge#81 train=0.0138004 test=0 default=0 src=live_history (0.0s) [never hedged on test (0 by construction)]
      polymarket:5170772 ETHA   tested   n=59 train=35 purge=3 test=21 equity_delta_bridge#92 train=0.102095 test=0 default=0 src=live_history (0.0s) [never hedged on test (0 by construction)]
      polymarket:5062323 ETHA   tested   n=133 train=79 purge=7 test=47 crypto_reg_hedge#0 train=-0.0514557 test=-0.15524 default=-1.13528 src=live_history (0.0s)
      polymarket:5036103 IBIT   tested   n=144 train=86 purge=8 test=50 crypto_reg_hedge#47 train=0.0221938 test=0.000855846 default=0.0361153 src=live_history (0.0s)
      polymarket:5036098 IBIT   tested   n=144 train=86 purge=8 test=50 crypto_reg_hedge#74 train=0.0278773 test=0.0452922 default=0.0145124 src=live_history (0.0s)
      polymarket:4713962 ITA    tested   n=352 train=211 purge=18 test=123 energy_geo_hedge#54 train=0.630513 test=-0.418305 default=-0.0221241 src=live_history (0.0s)
      polymarket:4985057 IBIT   tested   n=169 train=101 purge=9 test=59 equity_delta_bridge#101 train=0.0255933 test=0 default=0 src=live_history (0.0s) [never hedged on test (0 by construction)]
      polymarket:5170732 IBIT   tested   n=59 train=35 purge=3 test=21 equity_delta_bridge#102 train=0.441311 test=0 default=0 src=live_history (0.0s) [never hedged on test (0 by construction)]
      polymarket:4951230 XLE    tested   n=191 train=114 purge=10 test=67 equity_delta_bridge#29 train=0.0180161 test=-0.00066344 default=-0.00108603 src=live_history (0.0s)
      polymarket:4662695 AMZN   tested   n=378 train=226 purge=19 test=133 tech_reg_hedge#0 train=-0.00039113 test=-0.00081531 default=-0.00227627 src=live_history (0.0s)
      polymarket:2774057 XLE    tested   n=720 train=432 purge=36 test=252 equity_delta_bridge#85 train=0.00392578 test=0 default=0 src=live_history (0.0s) [never hedged on test (0 by construction)]
       polymarket:562794 XLE    tested   n=718 train=430 purge=36 test=252 equity_delta_bridge#48 train=0.00124185 test=-0.0318114 default=-0.0318114 src=live_history (0.0s)
      polymarket:5170734 MSTR   tested   n=59 train=35 purge=3 test=21 equity_delta_bridge#15 train=0.00613024 test=0 default=0 src=live_history (0.0s) [never hedged on test (0 by construction)]
      polymarket:1090496 ITA    tested   n=721 train=432 purge=37 test=252 equity_delta_bridge#96 train=0.0140639 test=-0.514653 default=-0.0556103 src=live_history (0.0s)
      polymarket:5170745 MSTR   tested   n=60 train=36 purge=3 test=21 equity_delta_bridge#90 train=0.00333411 test=0 default=0 src=live_history (0.0s) [never hedged on test (0 by construction)]
      polymarket:4885967 XLE    tested   n=238 train=142 purge=12 test=84 equity_delta_bridge#9 train=-0.018615 test=0.0141497 default=0.058406 src=live_history (0.0s)
      polymarket:5170743 MSTR   tested   n=59 train=35 purge=3 test=21 equity_delta_bridge#84 train=0.010136 test=0 default=0 src=live_history (0.0s) [never hedged on test (0 by construction)]
      polymarket:4936100 XLE    tested   n=204 train=122 purge=11 test=71 equity_delta_bridge#9 train=-0.0501483 test=-0.015572 default=-0.0646805 src=live_history (0.0s)
      polymarket:3554662 GOOGL  tested   n=720 train=432 purge=36 test=252 equity_delta_bridge#21 train=0.000559726 test=0 default=-0.00253053 src=live_history (0.0s) [never hedged on test (0 by construction)]
      polymarket:2467206 MSTR   tested   n=719 train=431 purge=36 test=252 crypto_reg_hedge#32 train=0.0898766 test=0.0190584 default=-0.0364474 src=live_history (0.0s)
      polymarket:5126794 DLR    tested   n=96 train=57 purge=5 test=34 equity_delta_bridge#84 train=0.00319815 test=-0.0679224 default=-0.0330246 src=live_history (0.0s)
      polymarket:5062329 COIN   tested   n=133 train=79 purge=7 test=47 equity_delta_bridge#9 train=4.93049e-05 test=0 default=-0.0156776 src=live_history (0.0s) [never hedged on test (0 by construction)]
      polymarket:3554658 META   tested   n=718 train=430 purge=36 test=252 tech_reg_hedge#60 train=0.388789 test=-7.65333 default=-0.395045 src=live_history (0.0s)
       polymarket:701488 MSTR   tested   n=719 train=431 purge=36 test=252 equity_delta_bridge#0 train=0.000292118 test=0.000586058 default=-0.0148702 src=live_history (0.0s)
      polymarket:4412200 MSFT   tested   n=577 train=346 purge=29 test=202 tech_reg_hedge#69 train=0.0449143 test=-4.0674 default=-0.588354 src=live_history (0.0s)
      polymarket:3399450 XLE    tested   n=720 train=432 purge=36 test=252 energy_geo_hedge#55 train=0.000113509 test=-0.00155424 default=0.000402447 src=live_history (0.0s)
      polymarket:5170729 MSTR   tested   n=59 train=35 purge=3 test=21 crypto_reg_hedge#74 train=0.163555 test=0 default=0 src=live_history (0.0s) [never hedged on test (0 by construction)]
      polymarket:1345531 MSTR   tested   n=719 train=431 purge=36 test=252 crypto_reg_hedge#8 train=0.0733942 test=-0.00265602 default=-0.0417775 src=live_history (0.0s)
      polymarket:3399468 XLE    tested   n=718 train=430 purge=36 test=252 energy_geo_hedge#28 train=0.00443458 test=-0.0939424 default=-0.0823047 src=live_history (0.0s)
      polymarket:5062285 MSTR   tested   n=133 train=79 purge=7 test=47 crypto_reg_hedge#25 train=0.00419678 test=0 default=0 src=live_history (0.0s) [never hedged on test (0 by construction)]
      polymarket:4936101 XLE    tested   n=205 train=123 purge=11 test=71 equity_delta_bridge#15 train=-0.0152725 test=-0.0510529 default=-0.168179 src=live_history (0.0s)
 kalshi:KXOAIANTH-40-OAI MSFT   tested   n=435 train=261 purge=22 test=152 tech_reg_hedge#15 train=-0.0684111 test=-0.0564806 default=-0.224946 src=live_history (0.0s)
kalshi:KXFUSION-30-JAN01 CCJ    tested   n=214 train=128 purge=11 test=75 stress_lead_hedge#54 train=0.0700795 test=-0.220235 default=-0.137718 src=live_history (0.0s)
kalshi:KXGDPYEAR-36-T0.1 SPY    tested   n=148 train=88 purge=8 test=52 macro_fed_hedge#45 train=0.130023 test=-0.154948 default=-0.154948 src=live_history (0.0s)
kalshi:KXFEDFUNDSYEAR-37JAN01-T1.00 TLT    tested   n=76 train=45 purge=4 test=27 equity_delta_bridge#0 train=-0.0123311 test=-0.0203288 default=-0.0677861 src=live_history (0.0s)
kalshi:KXGDPYEAR-35-T0.1 SPY    tested   n=196 train=117 purge=10 test=69 stress_lead_hedge#58 train=0.367311 test=-0.20857 default=0.0545447 src=live_history (0.0s)
kalshi:KXFEDFUNDSYEAR-36JAN01-T1.00 TLT    tested   n=161 train=96 purge=9 test=56 macro_fed_hedge#54 train=0.273849 test=0.0965918 default=0.261432 src=live_history (0.0s)
kalshi:KXGDPYEAR-34-T0.1 SPY    tested   n=231 train=138 purge=12 test=81 stress_lead_hedge#58 train=0.383553 test=-2.4974 default=-0.618582 src=live_history (0.0s)
kalshi:KXFEDFUNDSYEAR-35JAN01-T1.00 TLT    tested   n=99 train=59 purge=5 test=35 equity_delta_bridge#18 train=-0.000974362 test=-0.0265998 default=-0.0822661 src=live_history (0.0s)
kalshi:KXGDPYEAR-33-T0.1 SPY    tested   n=31 train=18 purge=2 test=11 equity_delta_bridge#0 train=-0.105911 test=-0.261476 default=-0.84974 src=live_history (0.0s)
```
