import React from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../../components/ui/card';
import { Button } from '../../components/ui/button';
import { FiCalendar, FiClock } from 'react-icons/fi';

const Matches = () => {
  return (
    <div className="container mx-auto p-6">
      <h1 className="text-3xl font-bold mb-6">Football Matches</h1>
      
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        {/* Example Match Card */}
        <Card>
          <CardHeader>
            <CardTitle>Manchester United vs Liverpool</CardTitle>
            <CardDescription className="flex items-center gap-2">
              <FiCalendar className="h-4 w-4" />
              <span>Premier League</span>
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-2">
                <FiClock className="h-4 w-4 text-muted-foreground" />
                <span>Today, 20:00</span>
              </div>
              <Button variant="outline" size="sm">View Odds</Button>
            </div>
            <div className="grid grid-cols-3 gap-2 text-center">
              <div className="p-2 bg-muted rounded-lg">
                <div className="text-sm font-medium">Home</div>
                <div className="text-lg font-bold">2.10</div>
              </div>
              <div className="p-2 bg-muted rounded-lg">
                <div className="text-sm font-medium">Draw</div>
                <div className="text-lg font-bold">3.40</div>
              </div>
              <div className="p-2 bg-muted rounded-lg">
                <div className="text-sm font-medium">Away</div>
                <div className="text-lg font-bold">2.80</div>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
};

export default Matches; 