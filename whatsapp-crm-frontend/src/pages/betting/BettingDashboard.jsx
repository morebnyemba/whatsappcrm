import React, { useEffect, useState } from 'react';
import axios from 'axios';

const BettingDashboard = () => {
  const [bettingData, setBettingData] = useState([]);

  useEffect(() => {
    const fetchBettingData = async () => {
      try {
        const response = await axios.get('/api/betting-data'); // Adjust the endpoint as needed
        setBettingData(response.data);
      } catch (error) {
        console.error('Error fetching betting data:', error);
      }
    };

    fetchBettingData();
  }, []);

  return (
    <div className="p-4">
      <h1 className="text-2xl font-bold mb-4">Betting Dashboard</h1>
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {bettingData.map((item, index) => (
          <div key={index} className="border p-4 rounded shadow">
            <h2 className="text-xl font-semibold">{item.title}</h2>
            <p>{item.description}</p>
          </div>
        ))}
      </div>
    </div>
  );
};

export default BettingDashboard; 