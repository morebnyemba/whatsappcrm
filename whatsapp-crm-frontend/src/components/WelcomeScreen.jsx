import React from 'react';
import { Link } from 'react-router-dom';
import { Button } from './ui/button';
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from './ui/card';
import { FiMessageSquare, FiUsers, FiShare2, FiAward, FiDollarSign } from 'react-icons/fi';

const FeatureCard = ({ icon: Icon, title, description }) => (
  <Card className="flex flex-col items-center text-center p-6 hover:shadow-lg transition-shadow duration-300">
    <div className="p-3 rounded-full bg-primary/10 mb-4">
      <Icon className="h-6 w-6 text-primary" />
    </div>
    <CardHeader className="p-0">
      <CardTitle className="text-xl">{title}</CardTitle>
    </CardHeader>
    <CardContent className="p-0 mt-2">
      <CardDescription>{description}</CardDescription>
    </CardContent>
  </Card>
);

const WelcomeScreen = () => {
  const features = [
    {
      icon: FiMessageSquare,
      title: "WhatsApp Integration",
      description: "Seamlessly manage your WhatsApp conversations and automate responses"
    },
    {
      icon: FiUsers,
      title: "Contact Management",
      description: "Organize and manage your contacts with advanced filtering and grouping"
    },
    {
      icon: FiShare2,
      title: "Flow Automation",
      description: "Create custom automation flows to streamline your communication"
    },
    {
      icon: FiAward,
      title: "Sports Betting",
      description: "Access real-time sports data and place bets through WhatsApp"
    },
    {
      icon: FiDollarSign,
      title: "Wallet Management",
      description: "Manage your betting wallet and track transactions securely"
    }
  ];

  return (
    <div className="min-h-screen bg-gradient-to-b from-background to-background/80">
      {/* Background Pattern */}
      <div className="absolute inset-0 bg-grid-pattern opacity-[0.02] pointer-events-none" />
      
      <div className="container relative mx-auto px-4 py-16 sm:px-6 lg:px-8">
        {/* Hero Section */}
        <div className="text-center mb-16">
          <h1 className="text-4xl font-bold tracking-tight sm:text-5xl md:text-6xl bg-gradient-to-r from-primary to-primary/60 bg-clip-text text-transparent">
            Welcome to AutoWhatsapp
          </h1>
          <p className="mt-6 text-lg text-muted-foreground max-w-2xl mx-auto">
            Your all-in-one solution for WhatsApp automation, contact management, and sports betting integration.
          </p>
          <div className="mt-8 flex justify-center gap-4">
            <Button asChild size="lg" className="rounded-full">
              <Link to="/login">
                Get Started
              </Link>
            </Button>
          </div>
        </div>

        {/* Features Grid */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-8 mt-16">
          {features.map((feature, index) => (
            <FeatureCard key={index} {...feature} />
          ))}
        </div>

        {/* Additional Info Section */}
        <div className="mt-24 text-center">
          <h2 className="text-2xl font-semibold mb-4">Ready to Get Started?</h2>
          <p className="text-muted-foreground mb-8">
            Join thousands of users who are already automating their WhatsApp communications
          </p>
          <Button asChild size="lg" className="rounded-full">
            <Link to="/login">
              Sign In Now
            </Link>
          </Button>
        </div>
      </div>

      {/* Footer */}
      <footer className="mt-24 border-t border-border/40">
        <div className="container mx-auto px-4 py-8 text-center text-sm text-muted-foreground">
          <p>© {new Date().getFullYear()} AutoWhatsapp. All rights reserved.</p>
        </div>
      </footer>
    </div>
  );
};

export default WelcomeScreen; 