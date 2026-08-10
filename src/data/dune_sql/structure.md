总体原则：
1. 不要改变任何最终呈现和逻辑，只改从dune上抓取信息的sql；
2. 所有能够多线程分为几个抓取任务同时抓取的都一起抓取，但不要让程序改出问题

After receiving the target token address

first step: get all pairs from uniswap v1-v4, balancer, curve
second step: get all history holders:
先用这个来写（正确表名是 balances_ethereum.daily_updates，不是旧的 balances.erc20_daily）：
SELECT DISTINCT address
FROM balances_ethereum.daily_updates
WHERE token_address = 0x...
  AND valid_from <= DATE '<to>'
  AND valid_to   >  DATE '<from>'   -- 稀疏区间，不是每天一行
  AND balance_raw > 0
但这个写法应该一天内买入卖出的人是读不到的，所以你也再把用transfer读from和to的写法也写上吧，但是先注释掉不要用
在holders抓取之后就按照现在程序的写法分辨是合约还是真实钱包

然后接下来是所有dashboard的需求
1. price timeline
后面应该会做成只有一个月、一周、一天这几个选项的
如果是一个月的时间 就按照每天0点抓所有池子的价格；如果是一周或者一天的就抓每个小时整点的。
然后就是从不同pool的price里面拿

2. trading volume
分池子做
从dex.trades这个里面拿数据，先筛block番位，然后筛交易币种，然后计算sum
分池算完以后加和算sum

4. pool distribution
直接用token_balance库抓每个库的余额

5. Balance distribution
如果是一个月的时间 就按照每天0点抓所有历史holder的balance；如果是一周或者一天的就抓每个小时整点的
用sim的token holders API，balance为0的自动隐藏
然后dashboard上面那个加号点开是lp的地方，v3的lp就还是按照现在的用tick去做

6. pool tvl
在时间节点算所有pool的balance*price 分别画折线，然后再相加画那一条总的
Balance和price都是每次直接抓取，不要累加算
时间节点：如果是一个月的时间 就按照每天0点；如果是一周或者一天的就抓每个小时整点的

7. 钱包聚类
先做批量取证数据源，把要采样的地址对都收集起来
整理成类似这样：
WITH candidates(address) AS (
    VALUES
        (0xAAA),
        (0xBBB),
        (0xCCC)
        -- ...
)
然后去transfer里面直接筛选查询reciprocal_transfer；
（抓取sender、receiver、amount、tx_hash、block_time）额我感觉sender和receiver是不是也不用抓 因为筛选条件就是这两个量，本地是不是本来就有
用GROUP BY sender, receiver找COUNT(*) >= 3，再判断金额相似程度。
然后用tx_hash去查ethereum.transactions，拿到gas payer；
再用tx_hash查ethereum.traces
最后用最早找地址的时候筛出来的合约的那部分地址，RPC 调 owner()，然后本地找 owner 相同的 contract。
