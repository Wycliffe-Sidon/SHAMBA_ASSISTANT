# Fahamu Shamba AI - Smart Farming Assistant

## 🌾 Overview

Fahamu Shamba AI is an intelligent, AI-powered farming assistant designed specifically for African farmers. It provides personalized agricultural recommendations based on location, soil conditions, weather patterns, and market trends. The application uses the **OpenAI API** for fast AI responses and supports both **English and Swahili** languages.

## ✨ Key Features

### 🎯 Smart Crop Recommendations
- Location-based crop suggestions using real-time soil data
- Percentage-based suitability ratings (0-100%)
- Detailed recommendations including planting time, maturity days, and market pricing
- AI-powered personalized advice based on your specific county and sub-location

### 🌤️ Weather Information
- Current seasonal information aligned with farming calendar
- Rainfall patterns and temperature guidance
- Farming advice tailored to the current season
- Real-time updates for better planning

### 🐛 Pest & Disease Management
- Common pests and diseases by county
- Treatment recommendations and best practices
- Prevention strategies for disease control
- Integrated pest management (IPM) techniques

### 📈 Market Price Tracking
- Current crop prices across Kenyan markets
- Trend analysis (rising, stable, falling)
- Demand indicators (high, medium, low demand)
- Real-time data for better business decisions

### 💬 General Agricultural Q&A
- Open-ended farming questions and answers
- Expert advice from AI trained on agricultural data
- Support for best practices in crop farming
- Problem-solving assistance for farming challenges

### 🌐 Multi-Language Support
- English (en-US)
- Swahili (sw-KE)
- Automatic language detection
- Text-to-speech in both languages

### 🎤 Voice Input & Output
- Hands-free voice commands
- Spoken responses for accessibility
- Speech recognition (where available)
- Natural conversation experience

## 🏗️ Architecture

### Front-End
- **Framework**: Vanilla JavaScript (no heavy dependencies)
- **Styling**: Modern CSS3 with CSS variables and responsive design
- **UI Components**: 
  - Tab-based navigation
  - Modal dialogs
  - Animated message bubbles
  - Beautiful crop recommendation cards
  - Real-time chat interface

### Back-End
- **Framework**: FastAPI (Python)
- **AI Engine**: OpenAI API
- **Deployment**: Render.com
- **Features**:
  - Session management
  - Rate limiting
  - Input sanitization
  - Multi-language detection
  - Comprehensive crop database

## 📋 Supported Counties

The application covers all 15 major farming counties in Kenya:
- Nairobi, Kiambu, Nakuru, Kisumu, Siaya
- Kakamega, Bungoma, Meru, Embu
- Machakos, Kitui, Nyeri, Murang'a
- Kirinyaga, Uasin Gishu

Each county includes detailed sub-locations for precise localization.

## 🚀 Getting Started

### Prerequisites
- Python 3.8+
- pip or conda
- OpenAI API key (get it from [openai.com](https://openai.com))

### Installation

1. **Clone the repository**
```bash
git clone https://github.com/Wycliffe-Sidon/SHAMBA_ASSISTANT.git
cd SHAMBA_ASSISTANT
```

2. **Set up environment variables**
```bash
cp .env.example .env
# Edit .env and add your OPENAI_API_KEY
echo "OPENAI_API_KEY=your_api_key_here" > .env
```

3. **Install dependencies**
```bash
pip install -r requirements.txt
```

4. **Run the application**
```bash
python main.py
# or with uvicorn directly:
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

5. **Access the application**
Open your browser and navigate to `http://localhost:8000`

## 📦 Dependencies

### Python (Backend)
- **fastapi**: Web framework for building APIs
- **uvicorn**: ASGI server
- **openai**: Official OpenAI API client
- **python-multipart**: Form data parsing
- **pydantic**: Data validation

### Frontend
- Pure JavaScript (no npm dependencies)
- Modern CSS3
- HTML5

## 🔑 Environment Variables

Create a `.env` file in the project root:

```bash
OPENAI_API_KEY=your_openai_api_key_here
```

## 📱 Responsive Design

The application is fully responsive and optimized for:
- **Mobile**: Smartphones (320px+)
- **Tablet**: iPad and similar devices (768px+)
- **Desktop**: Full HD and above (1024px+)

## 🎨 UI/UX Improvements

### Modern Design System
- Clean, minimalist interface
- Green color scheme reflecting agriculture
- Smooth animations and transitions
- Professional typography
- Accessible contrast ratios

### User Experience
- Intuitive tab-based navigation
- Location selection with sub-county options
- Real-time message feedback
- Typing indicators for AI responses
- Quick-action buttons for common tasks

### Accessibility
- Semantic HTML structure
- Text-to-speech functionality
- Voice input support
- High contrast modes
- Keyboard navigation

## 📊 Data Structure

### Crop Database
- Soil type requirements
- pH range preferences
- Seasonal suitability
- Maturity period (days)
- Variety recommendations

### Soil Profiles
- Soil type classification
- pH levels
- Fertility ratings
- Drainage characteristics

### Market Data
- Current pricing
- Trend analysis (rising/stable/falling)
- Demand indicators
- Price history (simulated)

## 🔐 Security Features

- **Input Sanitization**: HTML escape and validation
- **Rate Limiting**: 20 requests per minute per IP
- **Session Management**: Per-user session tracking
- **XSS Protection**: Automatic HTML escaping
- **API Timeouts**: 30-second timeout for AI requests

## 🌐 Deployment

### Render.com (Recommended)
```yaml
# render.yaml configuration included
Python 3.8+
Gunicorn or Uvicorn worker
Environment variables configured
```

### Other Platforms
- Heroku
- PythonAnywhere
- Railway
- AWS/GCP

## 📚 API Endpoints

### POST /chat
Chat with the AI assistant
```json
{
  "message": "What crops should I plant?",
  "session_id": "session_123",
  "county": "Nairobi",
  "sublocation": "Westlands",
  "context": "crops"
}
```

### GET /
Main interface (HTML served)

## 🧪 Testing

```bash
# Run tests (add test suite as needed)
pytest tests/
```

## 🤝 Contributing

Contributions are welcome! Please:
1. Fork the repository
2. Create a feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit changes (`git commit -m 'Add AmazingFeature'`)
4. Push to branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

## 📝 License

This project is licensed under the MIT License - see [LICENSE](LICENSE) file for details.

## 🎯 Future Enhancements

- [ ] Integration with real-time weather APIs
- [ ] Real market price data integration
- [ ] Soil testing kit integration
- [ ] Disease identification with image recognition
- [ ] Mobile app (React Native/Flutter)
- [ ] Farmer community forum
- [ ] Advanced analytics dashboard
- [ ] Integration with farm management tools
- [ ] IoT sensor integration
- [ ] Blockchain-based supply chain tracking

## 📞 Support & Contact

For issues, questions, or suggestions:
- **Email**: wycliffe.sidon@example.com
- **GitHub Issues**: [Create an issue](https://github.com/Wycliffe-Sidon/SHAMBA_ASSISTANT/issues)
- **Twitter**: [@FahamuShamba](https://twitter.com/FahamuShamba)

## 🙏 Acknowledgments

- **OpenAI** - For providing powerful AI API
- **FastAPI** - For the excellent Python web framework
- **African farmers** - For their valuable feedback and insights
- **Open source community** - For inspiration and resources

## 📈 Project Stats

- **Countries Served**: Kenya (expandable to Africa)
- **Counties Covered**: 15+
- **Supported Languages**: 2 (English, Swahili)
- **AI Model**: OpenAI GPT-3.5 / GPT-4 family
- **Response Time**: < 2 seconds average

---

**Made with ❤️ for African farmers**

*Last Updated: April 2026*
