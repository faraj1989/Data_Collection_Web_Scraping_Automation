""" i want to crate script to receive compliant from user in chat bot
 telegram_noc_bot.py so want to add button or ioption for complaint
 after that ask user to to send his coordinates after that match the nearest cell to the user in 2G,3G,4G
 mathc send ed uiser coordinates with list in below excell file name start with Libyana MS EPT in folder location
 F:\work\EPT\last update  you will find the excell start with Libyana MS EPT brib last updated file there y date created ,
 in this excell file there  is 3sheets GSM,UMTS and LTE
 in GSM sheet the header like below sheet:

Area	City	BSC Name	Site Name	BTS Name	BTS ID	Sector ID	Sector Name	Cell ID_DEC	Cell ID_HEX	Cell Name	Longitude	Latitude	Azimuth	Mechanical Tilt	Electric Tilt	Antenna Height (m)	LAC_DEC	LAC_HEX	Type	NCC	BCC	BSIC	BCCH	Active Status	number of TRX	Site Scenario 	Urban area
East	BGZ City	BGZMBSC01	BGZ070	BGZ070	1070	1	BGZ070-1	10701	29CD	BGZ070-1	20.08407	32.08265	15	2	4	21.5	4350	10FE	GSM900	3	5	35	110	ACTIVATED	4	DENSE URBAN	DU
East	BGZ City	BGZMBSC01	BGZ070	BGZ070	1070	2	BGZ070-2	10702	29CE	BGZ070-2	20.08407	32.08265	140	2	4	21.5	4350	10FE	GSM900	3	5	35	115	ACTIVATED	4	DENSE URBAN	DU
East	BGZ City	BGZMBSC01	BGZ070	BGZ070	1070	3	BGZ070-3	10703	29CF	BGZ070-3	20.08407	32.08265	240	2	4	21.5	4350	10FE	GSM900	3	5	35	121	ACTIVATED	4	DENSE URBAN	DU
East	BGZ City	BGZMBSC01	BGZ070	BGZ070	1070	1	BGZ070-1	10704	29D0	DBGZ070-1	20.08407	32.08265	15	2	4	21.5	4350	10FE	DCS1800	4	1	41	515	ACTIVATED	4	DENSE URBAN	DU
East	BGZ City	BGZMBSC01	BGZ070	BGZ070	1070	2	BGZ070-2	10705	29D1	DBGZ070-2	20.08407	32.08265	140	2	4	21.5	4350	10FE	DCS1800	5	2	52	522	ACTIVATED	4	DENSE URBAN	DU
East	BGZ City	BGZMBSC01	BGZ070	BGZ070	1070	3	BGZ070-3	10706	29D2	DBGZ070-3	20.08407	32.08265	240	2	4	21.5	4350	10FE	DCS1800	6	5	65	520	ACTIVATED	4	DENSE URBAN	DU


so after the user send his coordinates(user coordinates may be in decimal or hours,min,sec or shared link from google may we need to confirm ALL types of location ) match it with 	Longitude	Latitude	Azimuth
consider the azimuth to get best cell serving the user exact location
after that send the the cell or cells that nearest to the user. and check if this cells has issue with mains failure or ne is disconnected , if not has mains off alrm or check all alarms in files named

if i have the following table and user send its nearest cell name serving it how to make a python script to mactch the sent cell with all kpis and which kpi i can send him a reson for afftected user complaitn i wan to do all of that automaticaly in python scrait  user input cell name and python script send him backthe reseaon check all kpis below table and select the best reosn kpi afftcting user signal after that  i wan to send him a small reson user do not need to now the  exacly reson for his state andf why he is suferring

this excell sheet s in foldr in this project we already donwloaded by subscriers with 2G interference with ftp 31-5-26_v2.py
F:\python\2026\NAE NET Eco Scraping\Subscribers\Raw Data\20260531\unzipped\pythonAutoEastHGDaily-20260531080001
last foler name pythonAutoEastHGDaily contains ecxcell file name start with pythonAutoEastHGDaily- bring last updated one
inside thi sexcell you will find sheet named "Daily" its datawill be like below sample .

Date	GBSC	Cell CI	Cell Name	CellIndex	Site Name	Integrity	Downlink TBF Establishment Success Rate(%)	SDCCH Congestion Rate(%)	TCH Congestion Rate(%)	TCH Drop Rate(%)	SDCCH Drop Rate(%)	RR307:TCH Availability(%)	Call Setup Success Rate(%)	Handover Success Rate(%)	PS Traffic (RLC)(MB)	RCA313:Assignment Success Rate(%)	Immediate Assignment Success Rate(%)	K3014:Traffic Volume on TCH(Erl)	K3004:Traffic Volume on SDCCH(Erl)	TL9114:Average Throughput of Downlink GPRS RLC(kbit/s)	TL9333:Average Throughput of Downlink EGPRS RLC(kbit/s)	TL9232:Average Throughput of Uplink EGPRS RLC(kbit/s)	TL9014:Average Throughput of Uplink GPRS RLC(kbit/s)	TRX Availability Rate(%)	K3015:Available TCHs	K3016:Configured TCHs	Interference Band Proportion (4~5)(%)	Downlink HQI Proportion (0~5)(%)	Uplink HQI Proportion (0~5)(%)	CM33:Call Drops on Traffic Channel	K3013A:Successful TCH Seizures (Traffic Channel)	CH323:Number of Successful Incoming Internal Inter-Cell Handovers	CH343:Successful Incoming External Inter-Cell Handovers	CH313:Number of Successful Outgoing Internal Inter-Cell Handovers	CH333:Successful Outgoing External Inter-Cell Handovers
2026-05-30	SRTMBSC01	43183	SURT018-3	164	SURT018	100%	99.8294	0	0	0	0.2907	100	98.4774	96.4481	17.3222	100	98.7645	3.2056	2.3009	15.1805	6.2703	3.2948	10.4607	100	25.4113	25.4113	0.6909	95.7897	99.5799	0	174	259	0	353	0
2026-05-30	SRTMBSC01	43182	SURT018-2	163	SURT018	100%	98.4875	0	0	0.1044	0.2288	100	98.7332	98.3172	83.5385	99.7938	99.1641	15.3403	21.1963	20.5898	34.6595	15.6248	15.5799	100	24.8641	24.8641	0	98.3184	99.1848	2	484	1422	0	1519	0
2026-05-30	SRTMBSC01	43181	SURT018-1	162	SURT018	100%	97.5692	0	0	0.0605	0.3411	100	97.4678	98.9063	79.1194	99.6344	98.1603	12.482	21.0217	39.7541	34.3029	17.3292	27.9481	100	22.5889	22.5889	0.134	98.4566	98.9912	1	545	1106	0	1266	0
2026-05-30	SRTMBSC01	43173	SURT017-3	188	SURT017	100%	99.9177	0	0	0	0.1595	100	99.522	100	12.9799	100	99.681	2.8639	1.8787	18.3676	3.6733	1.4504	13.0747	100	25.0157	25.0157	0	99.4939	99.5336	0	127	154	0	242	0
2026-05-30	SRTMBSC01	43172	SURT017-2	187	SURT017	100%	98.7233	0	0	0	0.5272	100	95.318	97.1264	56.0855	100	95.8232	4.1875	4.2365	2.4658	21.568	8.6067	2.2754	100	25.5498	25.5498	0	98.1949	99.4376	0	173	229	0	338	0
2026-05-30	SRTMBSC01	43171	SURT017-1	186	SURT017	100%	99.7886	0	0	0	0.0801	100	98.7019	98.125	38.47	99.7135	99.0649	5.3278	5.654	31.1024	12.8749	5.6321	22.8493	100	23.76	23.76	0	98.3304	99.5907	0	348	312	0	471	0
2026-05-30	SRTMBSC01	43313	SURT031-3	100	SURT031	100%	98.1735	0	0	0.6897	0	100	98.7705	93.8144	2.3251	100	98.7705	1.2794	0.9537	0.236	1.4087	0.4754	0.2551	100	26.8664	26.8664	0	97.1925	99.6363	1	65	78	0	91	0
2026-05-30	SRTMBSC01	43312	SURT031-2	99	SURT031	100%	99.6843	0	0	0	0.1499	100	99.1231	99.7555	14.5405	100	99.2719	30.0755	7.1265	4.9399	9.8592	6.6452	4.6258	100	26.163	26.163	0	99.7104	99.8206	0	1141	379	0	408	0
2026-05-30	SRTMBSC01	43311	SURT031-1	98	SURT031	100%	98.7923	0	0	0	0.0499	100	99.1108	97.1471	293.5379	100	99.1602	27.6137	20.6571	19.8156	69.1851	32.9086	20.0846	100	23.7787	23.7787	0	98.609	98.8213	0	1164	627	0	647	0
2026-05-30	SRTMBSC01	43412	SURT041-2	114	SURT041	100%	98.622	0	0	0	0.0393	100	99.568	97.7956	34.8621	100	99.6071	14.4528	17.8188	2.8549	26.0113	12.3775	2.1351	100	26.0359	26.0359	0	98.3878	99.5212	0	581	476	0	488	0
2026-05-30	SRTMBSC01	43411	SURT041-1	113	SURT041	100%	98.2721	0	0	0.239	0.4249	100	97.7485	94.1901	62.0491	99.665	98.4955	19.2277	33.0784	12.7889	38.61	19.5274	9.2053	100	25.1596	25.1596	0	96.5527	99.7074	3	595	635	0	535	0
2026-05-30	SRTMBSC01	43413	SURT041-3	115	SURT041	100%	98.1362	0	0	0.1637	0.1703	100	98.5321	98.0174	130.9544	99.9125	98.7866	31.9222	44.5221	16.0378	56.6223	38.6909	16.964	100	10.9921	10.9921	0.0016	98.9285	98.3977	4	1142	1297	0	1236	0
2026-05-30	SRTMBSC01	43363	SURT036-3	170	SURT036	100%	99.7482	0	0	0.2548	0.2797	100	98.721	98.7143	133.1389	100	98.9979	4.7889	7.2574	64.8282	24.4149	14.2383	46.2708	100	20.1142	20.1142	9.5395	97.2359	98.8732	2	337	446	0	691	0
which kpis afftected the user complaint
can you do that in python scraipt in this proejct
 """