#!/Tsan/bin/python
# -*- coding: utf-8 -*-
# Libraries To Use
from __future__ import division
from CloudQuant import MiniSimulator
import numpy as np
import pandas as pd
import pdb
import cvxopt as cv
from cvxopt import solvers
from datetime import datetime, date, time


import factorFilterFunctions as ff

# define path
path = ff.data_path
filenameHS300 = 'LZ_GPA_INDXQUOTE_CLOSE.csv'
filenameICWeight = 'ICfactorWeight.csv'

# Variables and Constants
Init_Cap = 50000000
Start_Date = '20120101'
End_Date = '20161231'


ShortMA = 6
LongMA = 10
Period = 60
Position_Max = 200
rowsNum = 21
timeStampNum = 2000
thresholdNum = 0.2
indexPool = ['000300', '000905']

# Use own library to get the last day of each month
benchMarkData = pd.read_csv(path+filenameHS300, infer_datetime_format=True, parse_dates=[0], index_col=0)[-timeStampNum:]
startOfMonth, endOfMonth = ff.getLastDayOfMonth(benchMarkData.index)

# factor weight
factorWeight = pd.read_csv(path+filenameICWeight, infer_datetime_format=True, parse_dates=[0], index_col=0)

def getNewMatrix(inputArray, t, m):
    newMatrix = []
    n = t-m+1
    for i in range(n):
        newdata = list(inputArray[i:m+i])
        newMatrix.append(newdata)
    #newMatrix = np.array(newMatrix).reshape(n,m)
    return np.array(newMatrix)

def recreateArray(newMatrix,t,m):
    ret = []
    n = t - m + 1
    for p in range(1,t+1):
        if p < m:
            alpha = p
        elif p > t-m+1:
            alpha = t-p+1
        else:
            alpha = m
        sigma = 0
        for j in range(1, m+1):
            i = p - j + 1
            if i > 0 and i < n+1:
                sigma += newMatrix[i-1][j-1]
        ret.append(sigma/alpha)
    return np.array(ret)

def getSVD(inputArray,t,m):
    inputmatrix = getNewMatrix(inputArray, t, m)
    u, s, v = np.linalg.svd(inputmatrix)
    eviNum = 1 if s[0]/s.sum() > 0.99 else 2
    sNew = np.zeros((eviNum, eviNum))
    np.fill_diagonal(sNew, s[:eviNum])
    matrixForts = np.dot(np.dot(u[:, :eviNum].reshape(u.shape[0], eviNum), sNew), v[:eviNum])
    newts = recreateArray(matrixForts, t, m)
    return newts



def initial(sdk):
    sdk.prepareData(['LZ_GPA_INDEX_CSI500WEIGHT', 'LZ_GPA_VAL_PB', 'LZ_GPA_TURNOVER_TurnoverAvg_1M', 'LZ_GPA_FIN_IND_YOYBPS',
                     'LZ_GPA_DERI_ILLIQ', 'LZ_GPA_FIN_IND_PROFITTOOP',
                     'LZ_GPA_CMFTR_CUM_FACTOR', 'LZ_GPA_QUOTE_TCLOSE', 'LZ_GPA_INDXQUOTE_CLOSE'])
    dateList = map(lambda x: x.date().strftime("%Y%m%d"), endOfMonth)  # change time stamp to string
    sdk.setGlobal('dateList', dateList)
    sdk.setGlobal('sellSignal', [True])



def initPerDay(sdk):
    today = sdk.getNowDate()
    dateList = sdk.getGlobal('dateList')
    if today in dateList:  # judge whether today is the last day of the month
        stockPool = pd.DataFrame(np.array(sdk.getFieldData('LZ_GPA_INDEX_CSI500WEIGHT')[-20:]), columns=sdk.getStockList())
        stockPool = stockPool.iloc[-1].dropna(how='any').index.tolist()  # get today's ZX500 stock pool
        # PBData
        PBDF = pd.DataFrame(np.array(sdk.getFieldData('LZ_GPA_VAL_PB')[-20:]), columns=sdk.getStockList())
        PBDF = PBDF[stockPool].fillna(method='ffill').fillna(method='bfill').iloc[-1]
        PBSlice = (PBDF - PBDF.mean())/PBDF.std()  # normalize
        # MOM3MDFData
        TO1MDF = pd.DataFrame(np.array(sdk.getFieldData('LZ_GPA_TURNOVER_TurnoverAvg_1M')[-20:]), columns=sdk.getStockList())
        TO1MDF = TO1MDF[stockPool].fillna(method='ffill').fillna(method='bfill').iloc[-1]
        TO1MSlice = (TO1MDF - TO1MDF.mean())/TO1MDF.std()
        # PROFITTOOPData
        PROFITTOOPDF = pd.DataFrame(np.array(sdk.getFieldData('LZ_GPA_FIN_IND_PROFITTOOP')[-20:]), columns=sdk.getStockList())
        PROFITTOOPDF = PROFITTOOPDF[stockPool].fillna(method='ffill').fillna(method='bfill').iloc[-1]
        PROFITTOOPSlice = (PROFITTOOPDF - PROFITTOOPDF.mean())/PROFITTOOPDF.std()
        # YOYBPSData
        YOYBPSDF = pd.DataFrame(np.array(sdk.getFieldData('LZ_GPA_FIN_IND_YOYBPS')[-20:]), columns=sdk.getStockList())
        YOYBPSDF = YOYBPSDF[stockPool].fillna(method='ffill').fillna(method='bfill').iloc[-1]
        YOYBPSlice = (YOYBPSDF-YOYBPSDF.mean())/YOYBPSDF.std()
        # ILLIQData
        ILLIQDF = pd.DataFrame(np.array(sdk.getFieldData('LZ_GPA_DERI_ILLIQ')[-20:]), columns=sdk.getStockList())
        ILLIQDF = ILLIQDF[stockPool].fillna(method='ffill').fillna(method='bfill').iloc[-1]
        ILLIQSlice = (ILLIQDF-ILLIQDF.mean())/ILLIQDF.std()
        # Select the corresponding factor weight
        today = datetime.strptime(today, '%Y%m%d')
        WeightSlice = factorWeight.loc[today]
        finalIndictor = WeightSlice['PB'] * PBSlice + WeightSlice['TURNOVER_1M'] * TO1MSlice + \
                        WeightSlice['PROFITTOOP'] * PROFITTOOPSlice + WeightSlice['YOYBPS'] * YOYBPSlice + \
                        WeightSlice['ILLIQ'] * ILLIQSlice
        stocksTobuy = finalIndictor.sort_values(ascending=False).index.tolist()[:Position_Max]
        sdk.setGlobal('buyList', stocksTobuy)

        # To calculate the realized volatility matrix
        CPData = np.array(sdk.getFieldData('LZ_GPA_QUOTE_TCLOSE')[-251:])
        ClosePriceDF = pd.DataFrame(CPData, columns=sdk.getStockList())[stocksTobuy]
        ADfactor = np.array(sdk.getFieldData('LZ_GPA_CMFTR_CUM_FACTOR')[-251:])
        ADfactorDF = pd.DataFrame(ADfactor, columns=sdk.getStockList())[stocksTobuy]
        AdForward = ADfactorDF / ADfactorDF.max()
        adjustedPrice = (AdForward * ClosePriceDF)
        adjustedPrice = adjustedPrice.loc[:, adjustedPrice.isnull().sum() < (len(adjustedPrice) * thresholdNum)]
        #covMatrix = adjustedPrice.ewm(ignore_na=True, min_periods=0, com=10).cov(pairwise = True)[-60:].iloc[-1]
        adjustedPrice = np.log(adjustedPrice/adjustedPrice.shift(1))[-250:]  # calculate daily log return of each stock
        covMatrix = adjustedPrice.cov(1)
        #covMatrix.values

        # Quadratic Optimizaiton
        stkNum = covMatrix.shape[1]
        P = cv.matrix(covMatrix.values)
        q = cv.matrix(0.0, (stkNum, 1))
        G = cv.matrix(np.concatenate((np.diag(np.ones(stkNum)), - np.diag(np.ones(stkNum)))))
        h = cv.matrix(np.append(0.01 * np.ones(stkNum), np.zeros(stkNum)))
        A = cv.matrix(np.ones(stkNum)).T
        b = cv.matrix(1.0).T
        sol = solvers.qp(P, q, G, h, A, b)
        print sol['x']  # this shows the desired x weight
        # Add percentage of total Asset to reduce max drawdowm
        stocksWeightTarget = pd.Series(data=sol['x'] * sdk.getAccountAsset().previousAsset, index=covMatrix.columns)
        quotes = sdk.getQuotes(covMatrix.columns)
        noNoneData = list(set(covMatrix.columns) & set(quotes.keys()))
        stocksWeightTarget = stocksWeightTarget.loc[noNoneData]
        for stk in stocksWeightTarget.index:
            stocksWeightTarget.loc[stk] = stocksWeightTarget.loc[stk] / quotes[stk].open
        positionIndicator = sdk.getPositions()
        # stockPrices = pd.Series(data = np.array([i.open for i in positionIndicator]), index = covMatrix.columns)
        # stocksWeightTarget = stocksWeightTarget / stockPrices
        stocksWeightCurrently = pd.Series(data=[i.optPosition for i in positionIndicator], index=[i.code for i in positionIndicator])

        stocksTarget = stocksWeightTarget.index.tolist()
        stocksCurrent = stocksWeightCurrently.index.tolist()
        finalWeight = pd.Series(index=list(set(stocksTarget) | set(stocksCurrent)), data=None)

        intersection = list(set(stocksCurrent) & set(stocksTarget))
        differenceSell = list(set(stocksCurrent) - set(stocksTarget))
        differenceBuy = list(set(stocksTarget) - set(stocksCurrent))

        finalWeight.loc[intersection] = stocksWeightTarget.loc[intersection] - stocksWeightCurrently.loc[intersection]
        finalWeight.loc[differenceSell] = - stocksWeightCurrently.loc[differenceSell]
        finalWeight.loc[differenceBuy] = stocksWeightTarget.loc[differenceBuy]

        sdk.setGlobal('finalWeight', finalWeight)
        #adjustedPrice.dropna(axis=1, how='any', inplace=True)

        # quote all stocks
        positionStocks = [i.code for i in sdk.getPositions()]  ## Stocks we currently  hold
        totalPool = np.array(list(set(stocksTobuy) | set(positionStocks)))
        # print (stockPool)
        # sdk.subscribeQuote(stockPool)  ##subscribe
        sdk.setGlobal('POOL', totalPool)

        #print stockPool
    #print today


# ret = []
# for stock in sdk.getGlobal("POOL"):
# late = [i.close for i in sdk.getLatest(code=stock, count=period)]
# mean = np.nanmean(late)
# ret.append(mean)
# return np.array(ret)

## Trading function
def buyStocks(sdk, finalWeight, quotes):  # stockToBuy  is a pd.Series
    quoteStocks = quotes.keys()
    stockToBuy = list(set(finalWeight[finalWeight > 0].index.tolist()) & set(quoteStocks))
    asset = sdk.getAccountInfo()
    codeList = [i.code for i in sdk.getPositions()]
    # print sdk.getPositions()
    if stockToBuy and asset:
        if len(codeList) < Position_Max:
            if len(codeList) + len(stockToBuy) > Position_Max:
                frozenStk = frozenset(stockToBuy)
                spareList = sdk.getGlobal('buyList')
                stockToBuy = [x for x in spareList if x in frozenStk][:Position_Max - len(codeList)]
            orders = []
            for stock in stockToBuy:
                #assert np.any(quotes)  # judge whether quotes is None
                buyPrice = quotes[stock].open
                buyAmount = finalWeight.loc[stock]  # Can also buy half of the amount
                if buyPrice > 0 and buyAmount > 100:
                    orders.append([stock, buyPrice, int(np.floor(buyAmount / 100)) * 100, 'BUY'])
            sdk.makeOrders(orders)
            sdk.sdklog(orders, 'buy')  # Add this trade into log


def sellStocks(sdk, finalWeight, quotes):
    quoteStocks = quotes.keys()
    stockToSell = list(set(finalWeight[finalWeight < 0].index.tolist()) & set(quoteStocks))

    if stockToSell:
        orders = []
        positions = sdk.getPositions()  # check the amount of stock we cuurently hold
        for pos in positions:
            if pos.code in stockToSell:
                sellPrice = quotes[pos.code].open
                sellAmount = pos.optPosition
                if sellPrice > 0 and sellAmount > 100:
                    orders.append([pos.code, sellPrice, sellAmount, 'SELL'])
        sdk.makeOrders(orders)
        sdk.sdklog(orders, 'sell')  ## Add this trade into log

        # def cancelAllOrdersInq(sdk):
        # ods = sdk.getQueueOrders()

def sellAllStocks(sdk, stockToSell, quotes):
    quoteStocks = quotes.keys()
    stockToSell = list(set(stockToSell) & set(quoteStocks))

    if stockToSell:
        orders = []
        positions = sdk.getPositions()  # check the amount of stock we cuurently hold
        for pos in positions:
            if pos.code in stockToSell:
                sellPrice = quotes[pos.code].open
                sellAmount = pos.optPosition
                if sellPrice > 0 and sellAmount > 100:
                    orders.append([pos.code, sellPrice, sellAmount, 'SELL'])
        sdk.makeOrders(orders)

        sdk.sdklog(orders, 'sell')  ## Add this trade into log


def cutLose(sdk,thresholdNum,period):   # cut lose function
    codeList = [i.code for i in sdk.getPositions()]
    quotes = sdk.getQuotes(codeList)
    closePriceDF = pd.DataFrame(np.array(sdk.getFieldData('LZ_GPA_QUOTE_TCLOSE')[-period:]),
                                columns=sdk.getStockList())[quotes.keys()]
    ADfactor = np.array(sdk.getFieldData('LZ_GPA_CMFTR_CUM_FACTOR')[-period:])
    ADfactorDF = pd.DataFrame(ADfactor, columns=sdk.getStockList())[quotes.keys()]
    AdForward = ADfactorDF / ADfactorDF.max()
    closePriceDF = (AdForward * closePriceDF)
    maxPrice = closePriceDF.iloc[:-1].max()
    return closePriceDF.loc[:, (closePriceDF.iloc[-1] < (1-thresholdNum) * maxPrice).values].columns.tolist()


#  Main section
def strategy(sdk):
    '''market timing by svd, check whether HS300 index and ZZ500 index is surging up or plunged'''
    sellSignalList = sdk.getGlobal('sellSignal')
    indexDF = pd.DataFrame(np.array(sdk.getFieldData('LZ_GPA_INDXQUOTE_CLOSE')[-22:]), columns=sdk.getIndexList())
    # print sdk.getIndexList()
    indexDF = indexDF[indexPool]
    indexDF = indexDF.fillna(method='ffill').fillna(method='bfill')[-LongMA:]
    # if (indexDF.loc[:, indexDF.iloc[-1] == indexDF.iloc[-5:].min()].shape[1] == 2) and \
    #        (indexDF.loc[:, indexDF.iloc[-1] < indexDF.iloc[-12:].mean()].shape[1] == 2):
    SH300SVD = getSVD(indexDF[indexPool[0]].values, len(indexDF), ShortMA)
    ZZ500SVD = getSVD(indexDF[indexPool[1]].values, len(indexDF), ShortMA)
    if SH300SVD[-2] < indexDF[indexPool[0]].iloc[-2] and SH300SVD[-1] > indexDF[indexPool[0]].iloc[-1] and \
                    ZZ500SVD[-2] < indexDF[indexPool[1]].iloc[-2] and ZZ500SVD[-1] > indexDF[indexPool[1]].iloc[-1]:
        sellAllFlag = True
    else:
        sellAllFlag = False
    sellSignalList.append(sellAllFlag)
    sdk.setGlobal('sellSignal', sellSignalList)  # add sell signal to list
    if sellSignalList[-2] and sellSignalList[-1]:
        HoldingList = [i.code for i in sdk.getPositions()]
        quotes = sdk.getQuotes(HoldingList)
        stockToSell = HoldingList
        if stockToSell:
            sellAllStocks(sdk, stockToSell, quotes)

    else:   # if no sell all triggered, normally trade
        today = sdk.getNowDate()
        dateList = sdk.getGlobal('dateList')
        cutLoseList = cutLose(sdk, 0.08, 5)   # cut lose
        quotes = sdk.getQuotes(cutLoseList)
        if cutLoseList:
            sellAllStocks(sdk, cutLoseList, quotes)
        if today in dateList:    # if today is the last day of the month
            sdk.sdklog(sdk.getNowDate(), 'now')
            tempoPool = sdk.getGlobal('POOL')
            quotes = sdk.getQuotes(tempoPool)
            finalWeight = sdk.getGlobal('finalWeight')

            if len(finalWeight[finalWeight < 0]) > 0:  # sell stocks with negative weights
                sellStocks(sdk, finalWeight, quotes)

            #sdk.setGlobal('StkCurrentlyHolding', [i.code for i in sdk.getPositions()])
            if len(finalWeight[finalWeight > 0]) > 0:
                buyStocks(sdk, finalWeight, quotes)



def main():
    config = {'username': 'toriphy', 'password': '1991toriphy', 'rootpath': 'D:/cStrategy/',
              'initCapitalStock': Init_Cap,
              'startDate': Start_Date, 'endDate': End_Date, 'cycle': 1, 'executeMode': 'D', 'feeRate': 0.0015,
              'feeLimit': 5, 'strategyName': 'min_risk-cutloss(0.08,5)-shortMA6-cov250', 'logfile': 'ma.log', 'dealByVolume': True,
              'memorySize': 5,
              'initial': initial, 'preparePerDay': initPerDay, 'strategy': strategy}
    MiniSimulator(**config).run()


if __name__ == "__main__":
     main()