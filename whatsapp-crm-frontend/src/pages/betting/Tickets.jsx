import React from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../../components/ui/card';
import { Button } from '../../components/ui/button';
import { FiPlus, FiAward } from 'react-icons/fi';

const Tickets = () => {
  return (
    <div className="container mx-auto p-6">
      <div className="flex justify-between items-center mb-6">
        <h1 className="text-3xl font-bold">My Betting Tickets</h1>
        <Button className="flex items-center gap-2">
          <FiPlus className="h-4 w-4" />
          New Ticket
        </Button>
      </div>
      
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        {/* Example Ticket Card */}
        <Card>
          <CardHeader>
            <div className="flex justify-between items-start">
              <div>
                <CardTitle>Ticket #1234</CardTitle>
                <CardDescription>Created 2 hours ago</CardDescription>
              </div>
              <span className="px-2 py-1 bg-yellow-100 text-yellow-800 rounded-full text-sm font-medium">
                Pending
              </span>
            </div>
          </CardHeader>
          <CardContent>
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <FiAward className="h-4 w-4 text-muted-foreground" />
                  <span>Multiple Bet</span>
                </div>
                <span className="font-medium">3 selections</span>
              </div>
              
              <div className="space-y-2">
                <div className="flex justify-between text-sm">
                  <span>Total Stake:</span>
                  <span className="font-medium">$50.00</span>
                </div>
                <div className="flex justify-between text-sm">
                  <span>Potential Winnings:</span>
                  <span className="font-medium text-green-600">$250.00</span>
                </div>
                <div className="flex justify-between text-sm">
                  <span>Total Odds:</span>
                  <span className="font-medium">5.00</span>
                </div>
              </div>

              <Button variant="outline" className="w-full">View Details</Button>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
};

export default Tickets; 