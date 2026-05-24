@echo off
echo Pushing code to GitHub...
cd /d "c:\Users\rastr\Desktop\IMAGES CASS\cofffee ai\coffee-ai-platform"
git remote set-url origin https://github.com/Rastrith156/CoffeeGPT.git
git add .
git commit -m "Fix tests, requirements, and provider integrations"
git branch -M main
git push -u origin main --force-with-lease
echo.
echo Push complete!
pause
