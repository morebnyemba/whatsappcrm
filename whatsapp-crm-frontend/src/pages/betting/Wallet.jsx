import React from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../../components/ui/card';
import { Button } from '../../components/ui/button';
import { FiDollarSign, FiArrowUp, FiArrowDown } from 'react-icons/fi';

const Wallet = () => {
  return (
    <div className="container mx-auto p-6">
      <h1 className="text-3xl font-bold mb-6">My Wallet</h1>
      
      {/* Balance Card */}
      <Card className="mb-8">
        <CardHeader>
          <CardTitle>Current Balance</CardTitle>
          <CardDescription>Your available betting funds</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex items-baseline gap-2">
            <FiDollarSign className="h-6 w-6 text-primary" />
            <span className="text-4xl font-bold">1,250.00</span>
          </div>
          <div className="flex gap-4 mt-6">
            <Button className="flex-1">Deposit</Button>
            <Button variant="outline" className="flex-1">Withdraw</Button>
          </div>
        </CardContent>
      </Card>

      {/* Transaction History */}
      <div className="space-y-4">
        <h2 className="text-xl font-semibold">Transaction History</h2>
        
        <Card>
          <CardContent className="p-4">
            <div className="space-y-4">
              {/* Example Transaction */}
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <div className="p-2 bg-green-100 rounded-full">
                    <FiArrowUp className="h-4 w-4 text-green-600" />
                  </div>
                  <div>
                    <div className="font-medium">Deposit</div>
                    <div className="text-sm text-muted-foreground">2 hours ago</div>
                  </div>
                </div>
                <div className="text-right">
                  <div className="font-medium text-green-600">+$500.00</div>
                  <div className="text-sm text-muted-foreground">Bank Transfer</div>
                </div>
              </div>

              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <div className="p-2 bg-red-100 rounded-full">
                    <FiArrowDown className="h-4 w-4 text-red-600" />
                  </div>
                  <div>
                    <div className="font-medium">Bet Placed</div>
                    <div className="text-sm text-muted-foreground">1 hour ago</div>
                  </div>
                </div>
                <div className="text-right">
                  <div className="font-medium text-red-600">-$50.00</div>
                  <div className="text-sm text-muted-foreground">Ticket #1234</div>
                </div>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
};

export default Wallet; 