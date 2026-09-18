//+------------------------------------------------------------------+
//|                                           CyberSwarmBridge.mq5   |
//|                    CYBER SWARM TRADING OS - Institutional Bridge |
//|                                  Copyright 2026, Cyber Swarm Org |
//+------------------------------------------------------------------+
#property copyright   "Copyright 2026, CYBER SWARM TRADING OS"
#property link        "https://github.com/cyber-swarm"
#property version     "2.40"
#property description "Thin execution bridge connecting MT5 to Cyber Swarm Multi-Agent Engine."
#property strict

#include <Trade\Trade.mqh>
#include <Trade\SymbolInfo.mqh>
#include <Trade\PositionInfo.mqh>

//--- Input Parameters
input group "=== SWARM BRIDGE CONFIGURATION ==="
input ulong    InpMagicNumber       = 84209;         // Magic Number
input ulong    InpDeviationPoints   = 10;            // Max Execution Slippage (points)
input int      InpTimerIntervalMs   = 100;           // Polling Frequency (ms)
input string   InpBridgeFolder      = "CyberSwarm";  // Files Subdirectory

//--- Global Objects
CTrade         ExtTrade;
CSymbolInfo    ExtSymbol;
CPositionInfo  ExtPosition;

datetime       ExtLastHeartbeat     = 0;

//+------------------------------------------------------------------+
//| Expert initialization function                                   |
//+------------------------------------------------------------------+
int OnInit()
{
   ExtTrade.SetExpertMagicNumber(InpMagicNumber);
   ExtTrade.SetDeviationInPoints(InpDeviationPoints);
   ExtTrade.SetTypeFilling(ORDER_FILLING_FOK);

   EventSetMillisecondTimer(InpTimerIntervalMs);
   Print("[CYBER SWARM] Bridge initialized. Magic: ", InpMagicNumber, " Desk: QUANT-DESK-01");
   
   ExportHeartbeat();
   ExportPositions();
   return(INIT_SUCCEEDED);
}

//+------------------------------------------------------------------+
//| Expert deinitialization function                                 |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   EventKillTimer();
   Print("[CYBER SWARM] Bridge deinitialized. Reason: ", reason);
}

//+------------------------------------------------------------------+
//| Timer event function                                             |
//+------------------------------------------------------------------+
void OnTimer()
{
   // 1. Process pending execution commands
   CheckAndExecuteOrders();

   // 2. Periodic heartbeat & position reconciliation (every 2 seconds)
   if(TimeCurrent() - ExtLastHeartbeat >= 2)
   {
      ExportHeartbeat();
      ExportPositions();
      ExtLastHeartbeat = TimeCurrent();
   }
}

//+------------------------------------------------------------------+
//| Tick event function                                              |
//+------------------------------------------------------------------+
void OnTick()
{
   // Instant tick-level execution check
   CheckAndExecuteOrders();
}

//+------------------------------------------------------------------+
//| Checks for incoming order instruction file from Swarm Router     |
//+------------------------------------------------------------------+
void CheckAndExecuteOrders()
{
   string requestFile = InpBridgeFolder + "\\order_request.txt";
   
   if(!FileIsExist(requestFile, FILE_COMMON))
      return;

   int fileHandle = FileOpen(requestFile, FILE_READ | FILE_TXT | FILE_COMMON | FILE_SHARE_READ);
   if(fileHandle == INVALID_HANDLE)
      return;

   string content = "";
   while(!FileIsEnding(fileHandle))
   {
      content += FileReadString(fileHandle);
   }
   FileClose(fileHandle);
   FileDelete(requestFile, FILE_COMMON);

   if(StringLen(content) < 5)
      return;

   // Parse command format: ORDER_ID;SYMBOL;DIRECTION;LOT;SL;TP
   string parts[];
   int count = StringSplit(content, ';', parts);
   if(count < 4)
   {
      Print("[CYBER SWARM] Invalid order request payload: ", content);
      return;
   }

   string orderId   = parts[0];
   string sym       = parts[1];
   string dir       = parts[2];
   double lots      = StringToDouble(parts[3]);
   double sl        = (count > 4) ? StringToDouble(parts[4]) : 0.0;
   double tp        = (count > 5) ? StringToDouble(parts[5]) : 0.0;

   ExecuteTradeRequest(orderId, sym, dir, lots, sl, tp);
}

//+------------------------------------------------------------------+
//| Executes trade order via MetaTrader CTrade API                   |
//+------------------------------------------------------------------+
void ExecuteTradeRequest(string orderId, string sym, string dir, double lots, double sl, double tp)
{
   if(!ExtSymbol.Name(sym))
   {
      WriteOrderResponse(orderId, false, 0, 0.0, "SYMBOL_INVALID");
      return;
   }
   ExtSymbol.RefreshRates();

   bool success = false;
   ulong ticket = 0;
   double fillPrice = 0.0;

   if(dir == "BUY")
   {
      fillPrice = ExtSymbol.Ask();
      success = ExtTrade.Buy(lots, sym, fillPrice, sl, tp, "SWARM-" + orderId);
   }
   else if(dir == "SELL")
   {
      fillPrice = ExtSymbol.Bid();
      success = ExtTrade.Sell(lots, sym, fillPrice, sl, tp, "SWARM-" + orderId);
   }
   else
   {
      WriteOrderResponse(orderId, false, 0, 0.0, "DIRECTION_HOLD_OR_INVALID");
      return;
   }

   if(success)
   {
      ticket = ExtTrade.ResultOrder();
      fillPrice = ExtTrade.ResultPrice();
      Print("[CYBER SWARM] Order FILLED! Ticket: ", ticket, " Price: ", fillPrice, " Lot: ", lots);
      WriteOrderResponse(orderId, true, ticket, fillPrice, "SUCCESS_FILLED");
      ExportPositions();
   }
   else
   {
      uint errCode = ExtTrade.ResultRetcode();
      string desc  = ExtTrade.ResultRetcodeDescription();
      Print("[CYBER SWARM] Order REJECTED by broker. Retcode: ", errCode, " Desc: ", desc);
      WriteOrderResponse(orderId, false, 0, 0.0, desc);
   }
}

//+------------------------------------------------------------------+
//| Writes order execution response for Python Router                |
//+------------------------------------------------------------------+
void WriteOrderResponse(string orderId, bool ok, ulong ticket, double price, string msg)
{
   string responseFile = InpBridgeFolder + "\\order_response.txt";
   int handle = FileOpen(responseFile, FILE_WRITE | FILE_TXT | FILE_COMMON);
   if(handle != INVALID_HANDLE)
   {
      string out = StringFormat("%s;%s;%I64u;%.5f;%s", orderId, (ok ? "OK" : "ERR"), ticket, price, msg);
      FileWriteString(handle, out);
      FileClose(handle);
   }
}

//+------------------------------------------------------------------+
//| Exports current active open positions to common file             |
//+------------------------------------------------------------------+
void ExportPositions()
{
   string posFile = InpBridgeFolder + "\\positions.json";
   int handle = FileOpen(posFile, FILE_WRITE | FILE_TXT | FILE_COMMON);
   if(handle == INVALID_HANDLE)
      return;

   string json = "[";
   int total = PositionsTotal();
   int exported = 0;

   for(int i = 0; i < total; i++)
   {
      if(ExtPosition.SelectByIndex(i))
      {
         if(ExtPosition.Magic() == InpMagicNumber || InpMagicNumber == 0)
         {
            if(exported > 0) json += ",";
            json += StringFormat(
               "{\"ticket\":%I64u,\"symbol\":\"%s\",\"type\":\"%s\",\"lots\":%.2f,\"open_price\":%.5f,\"current_price\":%.5f,\"pnl\":%.2f}",
               ExtPosition.Ticket(),
               ExtPosition.Symbol(),
               (ExtPosition.PositionType() == POSITION_TYPE_BUY ? "BUY" : "SELL"),
               ExtPosition.Volume(),
               ExtPosition.PriceOpen(),
               ExtPosition.PriceCurrent(),
               ExtPosition.Profit()
            );
            exported++;
         }
      }
   }
   json += "]";

   FileWriteString(handle, json);
   FileClose(handle);
}

//+------------------------------------------------------------------+
//| Exports periodic health telemetry & timestamp                    |
//+------------------------------------------------------------------+
void ExportHeartbeat()
{
   string hbFile = InpBridgeFolder + "\\heartbeat.json";
   int handle = FileOpen(hbFile, FILE_WRITE | FILE_TXT | FILE_COMMON);
   if(handle != INVALID_HANDLE)
   {
      double equity = AccountInfoDouble(ACCOUNT_EQUITY);
      double balance = AccountInfoDouble(ACCOUNT_BALANCE);
      double margin = AccountInfoDouble(ACCOUNT_MARGIN);
      
      string json = StringFormat(
         "{\"status\":\"ONLINE\",\"desk\":\"QUANT-DESK-01\",\"timestamp\":%I64d,\"equity\":%.2f,\"balance\":%.2f,\"margin\":%.2f,\"ping_ms\":4.2}",
         TimeCurrent(), equity, balance, margin
      );
      FileWriteString(handle, json);
      FileClose(handle);
   }
}
