import React from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../../components/ui/card';
import { Button } from '../../components/ui/button';
import { FiUser, FiMail, FiPhone, FiSettings } from 'react-icons/fi';

const Profile = () => {
  return (
    <div className="container mx-auto p-6">
      <h1 className="text-3xl font-bold mb-6">My Profile</h1>
      
      {/* Profile Info */}
      <Card className="mb-8">
        <CardHeader>
          <CardTitle>Personal Information</CardTitle>
          <CardDescription>Your account details and preferences</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="space-y-6">
            <div className="flex items-center gap-4">
              <div className="p-3 bg-primary/10 rounded-full">
                <FiUser className="h-6 w-6 text-primary" />
              </div>
              <div>
                <div className="font-medium">John Doe</div>
                <div className="text-sm text-muted-foreground">Member since Jan 2024</div>
              </div>
            </div>

            <div className="grid gap-4">
              <div className="flex items-center gap-3">
                <FiMail className="h-5 w-5 text-muted-foreground" />
                <span>john.doe@example.com</span>
              </div>
              <div className="flex items-center gap-3">
                <FiPhone className="h-5 w-5 text-muted-foreground" />
                <span>+1 234 567 8900</span>
              </div>
            </div>

            <div className="pt-4 border-t">
              <Button className="w-full">
                <FiSettings className="mr-2 h-4 w-4" />
                Edit Profile
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Betting Stats */}
      <Card>
        <CardHeader>
          <CardTitle>Betting Statistics</CardTitle>
          <CardDescription>Your betting performance overview</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 gap-4">
            <div className="p-4 bg-muted rounded-lg">
              <div className="text-sm text-muted-foreground">Total Bets</div>
              <div className="text-2xl font-bold">24</div>
            </div>
            <div className="p-4 bg-muted rounded-lg">
              <div className="text-sm text-muted-foreground">Win Rate</div>
              <div className="text-2xl font-bold">65%</div>
            </div>
            <div className="p-4 bg-muted rounded-lg">
              <div className="text-sm text-muted-foreground">Total Winnings</div>
              <div className="text-2xl font-bold">$1,250</div>
            </div>
            <div className="p-4 bg-muted rounded-lg">
              <div className="text-sm text-muted-foreground">Active Tickets</div>
              <div className="text-2xl font-bold">3</div>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
};

export default Profile; 